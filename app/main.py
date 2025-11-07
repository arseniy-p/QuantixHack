# app/main.py
import base64
import json
import os
import httpx
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends, HTTPException, Response, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List

from . import models, schemas
from .database import SessionLocal, engine
from .s3_client import upload_file_to_s3

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

TELNYX_API_KEY = os.getenv("TELNYX_API_KEY")
TELNYX_API_BASE_URL = "https://api.telnyx.com/v2"
HEADERS = {
    "Authorization": f"Bearer {TELNYX_API_KEY}",
    "Content-Type": "application/json",
}

async def send_telnyx_command(call_control_id: str, command: str, params: dict = {}):
    """Асинхронно отправляет команду в Telnyx Call Control API."""
    url = f"{TELNYX_API_BASE_URL}/calls/{call_control_id}/actions/{command}"
    async with httpx.AsyncClient() as client:
        try:
            print(f"--> Sending command '{command}' to Telnyx for call {call_control_id} with params: {params}")
            response = await client.post(url, headers=HEADERS, json=params)
            response.raise_for_status()
            print(f"<-- Successfully sent command '{command}'. Response: {response.json()}")
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"!!! HTTP ERROR sending command '{command}': {e.response.status_code} - {e.response.text}")
        except Exception as e:
            print(f"!!! UNEXPECTED ERROR sending command '{command}': {e}")

# --- Webhooks by Telnyx ---

@app.post("/webhook/voice")
async def voice_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        data = await request.json()
        payload = data.get("data", {}).get("payload", {})
        event_type = data.get("data", {}).get("event_type")
        
        print(f"--- Webhook Received: {event_type} ---")
        
        call_control_id = payload.get("call_control_id")
        if not call_control_id:
            return Response(status_code=200)

        if event_type == "call.initiated":
            new_call = models.Call()
            new_call.call_control_id = payload["call_control_id"]
            new_call.call_sid = payload["call_session_id"]
            new_call.direction = payload["direction"]
            new_call.from_number = payload["from"]
            new_call.to_number = payload["to"]
            db.add(new_call)
            db.commit()
            print(f"Call {call_control_id} initiated and saved.")

            # В фоновом режиме отправляем команду "answer"
            background_tasks.add_task(send_telnyx_command, call_control_id, "answer")

        elif event_type == "call.answered":
            print(f"Call {call_control_id} was answered. Starting stream and recording.")
            
            # В фоновом режиме отправляем команды для стриминга и записи
            stream_params = {"stream_url": f"wss://{os.getenv('PUBLIC_HOST')}/ws/{call_control_id}"}
            record_params = {"format": "mp3", "channels": "single"}
            
            background_tasks.add_task(send_telnyx_command, call_control_id, "streaming_start", stream_params)
            background_tasks.add_task(send_telnyx_command, call_control_id, "record_start", record_params)

        elif event_type == "call.hangup":
            call = db.query(models.Call).filter_by(call_control_id=payload["call_control_id"]).first()
            if call:
                call.status = models.CallStatus.COMPLETED
                call.end_time = datetime.now()
                db.commit()

        elif event_type == "call.recording.saved":
            call = db.query(models.Call).filter_by(call_control_id=payload["call_control_id"]).first()
            if call:
                try:
                    recording_url = payload["recording_urls"]["mp3"]
                    file_name = f"{call.call_sid}.mp3"
                    
                    async with httpx.AsyncClient() as client:
                        response = await client.get(recording_url)
                        with open(file_name, "wb") as f:
                            f.write(response.content)

                    public_url = upload_file_to_s3(file_name, file_name)
                    os.remove(file_name) 

                    call.recording_url = public_url
                    call.recording_status = models.RecordingStatus.AVAILABLE
                    db.commit()
                except Exception as e:
                    call.recording_status = models.RecordingStatus.FAILED
                    db.commit()
                    print(f"Failed to process recording: {e}")

        return JSONResponse(content=[], media_type="application/json")

    except Exception as e:
        print(f"!!! MAJOR ERROR in webhook handler: {e}")
        import traceback
        traceback.print_exc()
        return Response(status_code=500)

# --- WebSocket for Real-time audio ---

@app.websocket("/ws/{call_control_id}")
async def websocket_endpoint(websocket: WebSocket, call_control_id: str): # УБРАЛИ Depends(get_db)
    await websocket.accept()
    print(f"WebSocket connection established for call: {call_control_id}")
    
    # --- РУЧНОЕ УПРАВЛЕНИЕ СЕССИЕЙ БД ---
    db = SessionLocal()
    try:
        # Обновляем статус звонка в БД на "активный"
        call = db.query(models.Call).filter_by(call_control_id=call_control_id).first()
        if call:
            call.status = models.CallStatus.ACTIVE
            db.commit()
            print(f"Call {call_control_id} status updated to ACTIVE.")
        else:
            print(f"WARNING: Call {call_control_id} not found in DB for status update.")

        # --- ЛОГИКА СОХРАНЕНИЯ АУДИО-ЧАНКОВ ---
        # Создаем уникальную папку для этого звонка
        call_audio_dir = f"audio_chunks/{call_control_id}"
        os.makedirs(call_audio_dir, exist_ok=True)
        print(f"Created directory for audio chunks: {call_audio_dir}")

        while True:
            message_str = await websocket.receive_text()
            message = json.loads(message_str)

            if message["event"] == "media":
                audio_chunk = base64.b64decode(message["media"]["payload"])
                
                # Генерируем уникальное имя файла с таймстампом
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                file_name = f"{call_audio_dir}/{timestamp}.raw"
                
                # Сохраняем байты аудио в файл
                with open(file_name, "wb") as f:
                    f.write(audio_chunk)
                    
                print(f"Saved audio chunk: {file_name} ({len(audio_chunk)} bytes)")

    except WebSocketDisconnect:
        print(f"WebSocket connection closed for call: {call_control_id}")
    except Exception as e:
        print(f"An error occurred in WebSocket for call {call_control_id}: {e}")
    finally:
        # --- ОБЯЗАТЕЛЬНО ЗАКРЫВАЕМ СЕССИЮ ---
        db.close()
        print(f"Database session closed for call {call_control_id}.")

# --- REST API for data retrival ---

@app.get("/calls", response_model=List[schemas.CallSchema])
def get_all_calls(db: Session = Depends(get_db)):
    """Get querry of all calls."""
    return db.query(models.Call).all()

@app.get("/calls/{call_id}", response_model=schemas.CallSchema)
def get_call_details(call_id: int, db: Session = Depends(get_db)):
    """Get detail info about call."""
    call = db.query(models.Call).filter_by(id=call_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    return call