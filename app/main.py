# app/main.py
import base64
import json
import os
import httpx
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends, HTTPException
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

# --- Webhooks by Telnyx ---

@app.post("/webhook/voice")
async def voice_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
        payload = data.get("data", {}).get("payload", {})
        event_type = data.get("data", {}).get("event_type")
        
        if event_type == "call.initiated":
            # Сохраняем информацию о звонке в БД
            new_call = models.Call(
                call_control_id=payload["call_control_id"],
                call_sid=payload["call_session_id"],
                direction=payload["direction"],
                from_number=payload["from"],
                to_number=payload["to"],
            )
            db.add(new_call)
            db.commit()
            print(f"Call {payload['call_control_id']} initiated and saved to DB.")

            # --- ИСПРАВЛЕННЫЙ ФОРМАТ КОМАНД ---
            call_control_id = payload["call_control_id"]
            commands = [
                {
                    "jsonrpc": "2.0",
                    "method": "call.answer",
                    "params": {"call_control_id": call_control_id}
                },
                {
                    "jsonrpc": "2.0",
                    "method": "call.record_start",
                    "params": {
                        "call_control_id": call_control_id,
                        "format": "mp3",
                        "channels": "single"
                    }
                },
                {
                    "jsonrpc": "2.0",
                    "method": "call.stream_start",
                    "params": {
                        "call_control_id": call_control_id,
                        "stream_url": f"wss://{os.getenv('PUBLIC_HOST')}/ws/{call_control_id}"
                    }
                }
            ]
            return commands

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

    except Exception as e:
        print(f"!!! ERROR in webhook: {e}")
        # В случае ошибки возвращаем HTTP 500, чтобы было видно в логах
        raise HTTPException(status_code=500, detail=str(e))

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