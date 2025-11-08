# filename: tts_engine.py

import os
import json
import base64
import asyncio
import websockets
import pyaudio
from datetime import datetime
from dotenv import load_dotenv

# --- Load API Keys ---
load_dotenv()
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

# --- Configuration ---
VOICE_ID = 'Xb7hH8MSUJpSbSDYk0k2'
MODEL_ID = 'eleven_turbo_v2'
OUTPUT_FORMAT = "pcm_24000"
SAMPLE_RATE = 24000
CHANNELS = 1
BIT_DEPTH_FORMAT = pyaudio.paInt16

# --- Helper for Timestamped Logging ---
def log_with_timestamp(message):
    now = datetime.now()
    timestamp = now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"
    print(f"[{timestamp}] {message}")

async def receive_and_play_audio(websocket):
    """Receives audio from ElevenLabs and plays it using PyAudio."""
    p = pyaudio.PyAudio()
    stream = p.open(format=BIT_DEPTH_FORMAT,
                    channels=CHANNELS,
                    rate=SAMPLE_RATE,
                    output=True)
    
    log_with_timestamp("Audio stream opened for playback.")
    try:
        async for message in websocket:
            data = json.loads(message)
            if data.get("audio"):
                audio_chunk = base64.b64decode(data["audio"])
                stream.write(audio_chunk)
            elif data.get('isFinal'):
                log_with_timestamp("Final audio received.")
                break
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()
        log_with_timestamp("Audio stream closed.")

# --- NEW: The main public function to be imported by other scripts ---
async def speak_text(text_to_speak: str):
    """
    Takes a string of text and streams it to ElevenLabs for real-time audio playback.
    This is the primary function to be imported.
    """
    if not ELEVENLABS_API_KEY:
        print("[TTS_ERROR] ELEVENLABS_API_KEY not set. Cannot perform text-to-speech.")
        return

    uri = f"wss://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/stream-input?model_id={MODEL_ID}"
    
    log_with_timestamp(f"TTS Engine: Starting audio for -> '{text_to_speak[:50]}...'")

    try:
        async with websockets.connect(uri) as websocket:
            # 1. Send initial configuration
            await websocket.send(json.dumps({
                "text": " ",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
                "output_format": OUTPUT_FORMAT,
                "xi_api_key": ELEVENLABS_API_KEY,
            }))

            # 2. Send the actual text payload
            await websocket.send(json.dumps({
                "text": text_to_speak,
                "try_trigger_generation": True
            }))

            # 3. Send end-of-stream signal
            await websocket.send(json.dumps({"text": ""}))

            # 4. Receive and play the audio
            await receive_and_play_audio(websocket)

    except Exception as e:
        log_with_timestamp(f"An error occurred in the TTS task: {e}")

# --- Main block to test this file directly ---
if __name__ == "__main__":
    # This part only runs when you execute "python tts_engine.py"
    # It serves as a simple test to ensure the TTS engine is working.
    test_sentence = "Hello, this is a direct test of the text to speech engine."
    print(f"Running a standalone test of the TTS engine...")
    
    if not ELEVENLABS_API_KEY:
        print("FATAL: The 'ELEVENLABS_API_KEY' environment variable is not set.")
    else:
        try:
            asyncio.run(speak_text(test_sentence))
        except KeyboardInterrupt:
            print("\nExiting test.")