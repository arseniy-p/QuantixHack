# filename: app/tts_service.py

import os
import json
import base64
import asyncio
import websockets
from datetime import datetime
from .logger_config import logger

# --- Configuration ---
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = 'Xb7hH8MSUJpSbSDYk0k2'  # Specify your desired voice ID
MODEL_ID = 'eleven_turbo_v2'

async def stream_tts_to_telnyx(
    text_to_speak: str,
    telnyx_websocket,
    call_control_id: str
):
    """
    Takes text, generates audio from ElevenLabs, and streams it back to the user via the Telnyx WebSocket.
    This is the core TTS function for the voicebot.
    """
    if not ELEVENLABS_API_KEY:
        logger.error("[TTS_ERROR] ELEVENLABS_API_KEY not set. Cannot perform text-to-speech.")
        return

    uri = f"wss://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/stream-input?model_id={MODEL_ID}"
    
    logger.info(f"TTS Engine: Starting audio stream for call {call_control_id} -> '{text_to_speak[:50]}...'")

    try:
        async with websockets.connect(uri) as websocket:
            await websocket.send(json.dumps({
                "text": " ",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
                "xi_api_key": ELEVENLABS_API_KEY,
            }))

            await websocket.send(json.dumps({
                "text": text_to_speak,
                "try_trigger_generation": True
            }))

            await websocket.send(json.dumps({"text": ""}))

            while True:
                try:
                    message_str = await websocket.recv()
                    message = json.loads(message_str)
                    
                    if message.get("audio"):
                        audio_chunk = base64.b64decode(message["audio"])

                        telnyx_payload = base64.b64encode(audio_chunk).decode('utf-8')
                        
                        await telnyx_websocket.send_text(json.dumps({
                            "event": "media",
                            "media": {
                                "payload": telnyx_payload
                            }
                        }))
                        
                    elif message.get('isFinal'):
                        logger.info("TTS stream finished for this text.")
                        break 
                        
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("ElevenLabs connection closed.")
                    break

    except Exception as e:
        logger.error(f"An error occurred in the TTS task for call {call_control_id}: {e}", exc_info=True)