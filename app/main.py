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
    data = await request.json()
    payload = data.get("data", {}).get("payload", {})
    event_type = data.get("data", {}).get("event_type")
    
    if event_type == "call.initiated":
        new_call = models.Call(
            call_control_id=payload["call_control_id"],
            call_sid=payload["call_session_id"],
            direction=payload["direction"],
            from_number=payload["from"],
            to_number=payload["to"],
        )
        db.add(new_call)
        db.commit()
        
        return [
            {"command": "answer", "call_control_id": payload["call_control_id"]},
            {"command": "record_start", "call_control_id": payload["call_control_id"], "format": "mp3", "channels": "single"},
            {"command": "stream_start", "call_control_id": payload["call_control_id"], "stream_url": f"wss://{os.getenv('PUBLIC_HOST')}/ws/{payload['call_control_id']}"}
        ]

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

    return {"status": "ok"}

# --- WebSocket for Real-time audio ---

@app.websocket("/ws/{call_control_id}")
async def websocket_endpoint(websocket: WebSocket, call_control_id: str, db: Session = Depends(get_db)):
    await websocket.accept()
    print(f"WebSocket connection established for call: {call_control_id}")
    
    call = db.query(models.Call).filter_by(call_control_id=call_control_id).first()
    if call:
        call.status = models.CallStatus.ACTIVE
        db.commit()

    try:
        while True:
            message_str = await websocket.receive_text()
            message = json.loads(message_str)
            if message["event"] == "media":
                audio_chunk = base64.b64decode(message["media"]["payload"])
                # !!! ЛОГИКА ВАШЕГО БОТА ЗДЕСЬ !!!
                # 1. Отправляем audio_chunk в Speech-to-Text
                # 2. Полученный текст отправляем в LLM
                # 3. Ответ LLM отправляем в ElevenLabs TTS
                # 4. Полученный аудиопоток отправляем обратно в WebSocket
                print(f"Received audio chunk of size: {len(audio_chunk)} bytes")
    except WebSocketDisconnect:
        print(f"WebSocket connection closed for call: {call_control_id}")

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