# app/main.py
import base64
import json
import os
import httpx
from datetime import datetime
from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    Request,
    Depends,
    HTTPException,
    Response,
    BackgroundTasks,
)
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List

from . import models, schemas
from .database import SessionLocal, engine
from .s3_client import upload_file_to_s3
from .logger_config import logger
from .call_processor import CallProcessor
from . import crud

import redis.asyncio as redis

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

@app.get("/test-redis")
async def test_redis_connection():
    """A simple endpoint to test writing and reading from Redis."""
    try:
        test_key = "test_key"
        test_value = datetime.now().isoformat()
        
        logger.info(f"--- Testing Redis Connection ---")
        await redis_client.set(test_key, test_value)
        logger.info(f"Successfully wrote to Redis: {{'{test_key}': '{test_value}'}}")
        
        retrieved_value = await redis_client.get(test_key)
        logger.info(f"Successfully read from Redis: '{retrieved_value}'")

        if retrieved_value == test_value:
            return {"status": "SUCCESS", "message": "Redis connection is working perfectly."}
        else:
            return {"status": "FAILURE", "message": "Read/write values do not match."}
            
    except Exception as e:
        logger.error(f"!!! Redis connection test failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Redis connection failed: {e}")



async def send_telnyx_command(call_control_id: str, command: str, params: dict = {}):
    url = f"{TELNYX_API_BASE_URL}/calls/{call_control_id}/actions/{command}"
    async with httpx.AsyncClient() as client:
        try:
            logger.info(
                f"--> Sending command '{command}' to Telnyx for call {call_control_id} with params: {params}"
            )
            response = await client.post(url, headers=HEADERS, json=params)
            response.raise_for_status()
            logger.info(
                f"<-- Successfully sent command '{command}'. Response: {response.json()}"
            )
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"!!! HTTP ERROR sending command '{command}': {e.response.status_code} - {e.response.text}"
            )
        except Exception as e:
            logger.error(f"!!! UNEXPECTED ERROR sending command '{command}': {e}")


redis_client = None

@app.on_event("startup")
async def startup_event():
    global redis_client
    redis_client = redis.Redis(
        host='redis-voicebot-svc',
        port=6379,
        password=os.getenv('REDIS_PASSWORD'), # <-- Добавьте пароль
        decode_responses=True
    )


async def set_latest_call_id_in_redis(redis_client, call_id: str):
    """
    Safely sets the latest call ID in Redis with logging and error handling.
    """
    try:
        logger.info(f"---> Setting 'latest_call_id' in Redis: {call_id}")
        await redis_client.set("latest_call_id", call_id)
        logger.info(f"<--- Successfully set 'latest_call_id' in Redis.")
    except Exception as e:
        logger.error(
            f"!!! FAILED to set 'latest_call_id' in Redis. Streamlit will not work. Error: {e}",
            exc_info=True # This will print the full traceback
        )


# --- Webhooks by Telnyx ---


@app.post("/webhook/voice")
async def voice_webhook(
    request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    try:
        data = await request.json()
        payload = data.get("data", {}).get("payload", {})
        event_type = data.get("data", {}).get("event_type")

        logger.info(f"--- Webhook Received: {event_type} ---")

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
            logger.info(f"Call {call_control_id} initiated and saved.")

            background_tasks.add_task(
                set_latest_call_id_in_redis, redis_client, call_control_id
            )

            background_tasks.add_task(send_telnyx_command, call_control_id, "answer")

        elif event_type == "call.answered":
            logger.info(
                f"Call {call_control_id} was answered. Starting stream and recording."
            )
            stream_params = {
                "stream_url": f"wss://{os.getenv('PUBLIC_HOST')}/ws/{call_control_id}"
            }
            record_params = {"format": "mp3", "channels": "single"}

            background_tasks.add_task(
                send_telnyx_command, call_control_id, "streaming_start", stream_params
            )
            background_tasks.add_task(
                send_telnyx_command, call_control_id, "record_start", record_params
            )

        elif event_type == "call.hangup":
            call = (
                db.query(models.Call)
                .filter_by(call_control_id=payload["call_control_id"])
                .first()
            )
            if call:
                call.status = models.CallStatus.COMPLETED
                call.end_time = datetime.now()
                db.commit()

        elif event_type == "call.recording.saved":
            call = (
                db.query(models.Call)
                .filter_by(call_control_id=payload["call_control_id"])
                .first()
            )
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
                    logger.error(
                        f"!!! MAJOR ERROR in webhook handler: {e}", exc_info=True
                    )

        return JSONResponse(content=[], media_type="application/json")

    except Exception as e:
        print(f"!!! MAJOR ERROR in webhook handler: {e}")
        import traceback

        traceback.print_exc()
        return Response(status_code=500)


# --- WebSocket for Real-time audio ---


@app.websocket("/ws/{call_control_id}")
async def websocket_endpoint(websocket: WebSocket, call_control_id: str):
    await websocket.accept()
    logger.info(f"WebSocket connection accepted for call: {call_control_id}")

    processor = CallProcessor(
        call_control_id=call_control_id,
        websocket=websocket,
        redis_client=redis_client 
    )
    await processor.run()


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

@app.post("/claims/search", response_model=List[schemas.ClaimSchema])
def search_for_claims(query: schemas.ClaimSearchQuery, db: Session = Depends(get_db)):
    """
    Real-time search endpoint for the voicebot.
    Receives keywords from NER and uses FTS to find relevant claims.
    """
    logger.info(f"Searching for claims with query: '{query.text}'")
    # In a real scenario, you'd also pass the user's phone number from the call record
    claims = crud.search_claims(db=db, query=query.text)
    if not claims:
        logger.warning(f"No claims found for query: '{query.text}'")
        # You can return a 404, but for a voicebot, an empty list is often better
        # raise HTTPException(status_code=404, detail="No claims found")
    return claims


# --- Standard CRUD endpoints for administration/testing ---

@app.post("/claims/", response_model=schemas.ClaimSchema)
def create_new_claim(claim: schemas.ClaimCreate, db: Session = Depends(get_db)):
    """
    Create a new claim.
    """
    return crud.create_claim(db=db, claim=claim)


@app.get("/claims/", response_model=List[schemas.ClaimSchema])
def read_all_claims(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Retrieve all claims with pagination.
    """
    claims = crud.get_all_claims(db, skip=skip, limit=limit)
    return claims


@app.get("/claims/{claim_id}", response_model=schemas.ClaimSchema)
def read_single_claim(claim_id: int, db: Session = Depends(get_db)):
    """
    Retrieve a single claim by its ID.
    """
    db_claim = crud.get_claim_by_id(db, claim_id=claim_id)
    if db_claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return db_claim
