import os
import json
import base64
import asyncio
import websockets
import pyaudio
from datetime import datetime
from dotenv import load_dotenv
from openai import AsyncOpenAI

# --- Load API Keys ---
load_dotenv()
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# --- Configuration ---
VOICE_ID = 'Xb7hH8MSUJpSbSDYk0k2'
MODEL_ID = 'eleven_turbo_v2'
LLM_MODEL = 'gpt-4'

# --- NEW: Audio Configuration for ElevenLabs and PyAudio ---
# We must match the output format from ElevenLabs with the PyAudio stream parameters.
# pcm_24000 is a good balance of quality and latency.
OUTPUT_FORMAT = "pcm_24000"
SAMPLE_RATE = 24000
CHANNELS = 1
# paInt16 is the PyAudio format for 16-bit audio, which matches the PCM data.
BIT_DEPTH_FORMAT = pyaudio.paInt16

# --- Initialize OpenAI Client ---
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# --- Helper for Timestamped Logging ---
def log_with_timestamp(message):
    now = datetime.now()
    timestamp = now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"
    print(f"[{timestamp}] {message}")

# --- LLM Task (No changes needed here) ---
async def llm_streaming_task(text_queue: asyncio.Queue):
    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{'role': 'user', 'content': 'Tell me a short story about the john pok'}],
            stream=True
        )
        log_with_timestamp("LLM stream started.")
        async for chunk in response:
            text_chunk = chunk.choices[0].delta.content
            if text_chunk:
                await text_queue.put(text_chunk)
                log_with_timestamp(f"LLM -> '{text_chunk}'")
    except Exception as e:
        log_with_timestamp(f"An error occurred in the LLM task: {e}")
    finally:
        await text_queue.put(None)
        log_with_timestamp("LLM stream finished.")


# --- Main TTS Task ---
async def tts_websocket_task(text_queue: asyncio.Queue):
    uri = f"wss://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/stream-input?model_id={MODEL_ID}"

    try:
        async with websockets.connect(uri) as websocket:
            # 1. Send initial configuration, INCLUDING THE AUDIO OUTPUT FORMAT
            await websocket.send(json.dumps({
                "text": " ",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
                "output_format": OUTPUT_FORMAT, # <-- Add this line
                "xi_api_key": ELEVENLABS_API_KEY,
            }))

            # 2. Concurrently run sender and receiver
            sender_task = asyncio.create_task(
                send_text_to_elevenlabs(websocket, text_queue)
            )
            receiver_task = asyncio.create_task(
                receive_and_play_audio(websocket) # <-- Use the new function
            )
            await asyncio.gather(sender_task, receiver_task)

    except Exception as e:
        log_with_timestamp(f"An error occurred in the TTS task: {e}")

# --- Text Sender Task (No changes needed here) ---
async def send_text_to_elevenlabs(websocket, text_queue):
    while True:
        text_chunk = await text_queue.get()
        if text_chunk is None:
            await websocket.send(json.dumps({"text": ""}))
            log_with_timestamp("TTS -> Sent end-of-stream signal.")
            break
        await websocket.send(json.dumps({
            "text": text_chunk + " ", "try_trigger_generation": True
        }))


# --- MODIFIED: Audio Receiver and Player Task ---
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
                # The core of real-time playback: write the chunk to the audio stream
                stream.write(audio_chunk)
                log_with_timestamp(f"TTS -> Played audio chunk of size: {len(audio_chunk)} bytes")
            elif data.get('isFinal'):
                log_with_timestamp("TTS -> Final audio received.")
                break
    finally:
        # Clean up the PyAudio stream and instance
        stream.stop_stream()
        stream.close()
        p.terminate()
        log_with_timestamp("Audio stream closed.")


# --- Main Function to run everything ---
async def main():
    text_queue = asyncio.Queue()
    llm_task = asyncio.create_task(llm_streaming_task(text_queue))
    tts_task = asyncio.create_task(tts_websocket_task(text_queue))
    await asyncio.gather(llm_task, tts_task)
    log_with_timestamp("Process complete.")


if __name__ == "__main__":
    asyncio.run(main())