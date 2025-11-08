# runpod_stt_worker/stt_server.py (НОВАЯ, ИСПРАВЛЕННАЯ ВЕРСЯ)

import asyncio
import websockets
import json
import os
import logging
from RealtimeSTT import AudioToTextRecorder
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time
import numpy as np

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - [%(levelname)s] - %(message)s",
)
logger = logging.getLogger(__name__)

# --- Health Check Server (без изменений) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode('utf-8'))
        else: self.send_response(404); self.end_headers()
    def log_message(self, format, *args): pass

def run_health_check_server():
    server_address = ('', 8080)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    logger.info("Health check server running on port 8080...")
    httpd.serve_forever()


# --- ИЗМЕНЕНИЕ: Теперь сессия сама управляет своим recorder'ом ---
class RealtimeSTTSession:
    def __init__(self, websocket):
        self.websocket = websocket
        self.recorder = None
        self.is_active = True
        self.last_transcript = ""
        self.transcript_lock = threading.Lock()
        
        # ### ИЗМЕНЕНИЕ 1: Запоминаем event loop при создании сессии ###
        # Мы находимся в `stt_handler`, который является async, поэтому здесь loop точно есть.
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.error("Could not get running event loop. This should not happen in stt_handler.")
            self.loop = None

    def _initialize_recorder(self):
        """Инициализация recorder'а для этой конкретной сессии."""
        logger.info("🔥 Initializing new RealtimeSTT recorder for session...")
        try:
            self.recorder = AudioToTextRecorder(
                model=os.getenv("MODEL_SIZE", "medium.en"),
                language="en",
                device="cuda",
                gpu_device_index=0,
                compute_type="float16",
                use_microphone=False,
                spinner=False,
                enable_realtime_transcription=True,
                realtime_model_type="tiny.en",
                realtime_processing_pause=0.1,
                
                # ### ФИНАЛЬНАЯ КОНФИГУРАЦИЯ VAD ###
                
                # WebRTC VAD: 0 - самый чувствительный режим. Пропустит почти всё.
                webrtc_sensitivity=0,
                
                # Silero VAD: 0.8 - очень высокая чувствительность.
                silero_sensitivity=0.8,
                
                # Включаем обратно внутренний VAD faster-whisper.
                # Это позволит ему самому найти речь в том потоке, что пропустит Silero/WebRTC.
                # Это исправляет ошибку 'No clip timestamps found'.
                faster_whisper_vad_filter=True, 
                
                # Остальные параметры
                silero_use_onnx=True,
                post_speech_silence_duration=0.8, # Немного увеличим, чтобы не обрывать фразы
                min_length_of_recording=0.4,      # Немного уменьшим для коротких ответов
                level=logging.WARNING
            )
            self.recorder.on_transcription_finished = self.on_transcription
            self.recorder.on_realtime_transcription_update = self.on_realtime_update
            self.recorder.start()
            logger.info("✅ Recorder initialized and worker thread started.")
        except Exception as e:
            logger.error(f"Failed to initialize recorder for session: {e}", exc_info=True)
            raise

    def on_transcription(self, text):
        if not self.is_active or not self.loop: return
        text = text.strip()
        if not text: return
        logger.info(f"📝 Final transcript: '{text}'")
        
        # ### ИЗМЕНЕНИЕ 2: Используем потокобезопасный метод для вызова async из sync ###
        asyncio.run_coroutine_threadsafe(
            self._send_transcript(text, is_final=True),
            self.loop
        )
    
    def on_realtime_update(self, text):
        if not self.is_active or not self.loop: return
        text = text.strip()
        with self.transcript_lock:
            if text and text != self.last_transcript:
                self.last_transcript = text
                
                # ### ИЗМЕНЕНИЕ 3: И здесь тоже используем потокобезопасный метод ###
                asyncio.run_coroutine_threadsafe(
                    self._send_transcript(text, is_final=False),
                    self.loop
                )

    # Эта функция остается async, так как ее вызывает run_coroutine_threadsafe
    async def _send_transcript(self, text, is_final):
        try:
            message = {
                "type": "transcript" if is_final else "interim_transcript",
                "text": text,
                "is_final": is_final
            }
            await self.websocket.send(json.dumps(message))
        except Exception as e:
            logger.error(f"Error sending transcript: {e}")
    
    def feed_audio(self, audio_chunk):
        if self.is_active and self.recorder:
            self.recorder.feed_audio(audio_chunk)
    
    def stop(self):
        self.is_active = False
        if self.recorder:
            try:
                self.recorder.shutdown()
                logger.info("Recorder shutdown completed.")
            except Exception as e:
                logger.error(f"Error during recorder shutdown: {e}")
        with self.transcript_lock:
            self.last_transcript = ""


# --- ИЗМЕНЕНИЕ: Убираем GlobalRecorderManager ---

async def stt_handler(websocket):
    """Обработчик WebSocket соединений. Теперь он проще."""
    client_addr = websocket.remote_address
    logger.info(f"🔌 Client connected from {client_addr}")
    
    # Создаем сессию, она пока пустая
    session = RealtimeSTTSession(websocket)
    
    try:
        # Инициализируем recorder ВНУТРИ сессии
        session._initialize_recorder()
        
        await websocket.send(json.dumps({ "type": "ready", "model": os.getenv("MODEL_SIZE", "medium.en") }))
        logger.info(f"✅ Session ready for {client_addr}")
        
        async for message in websocket:
            if isinstance(message, bytes):
                session.feed_audio(message)
        
    except websockets.exceptions.ConnectionClosed as e:
        logger.info(f"Client {client_addr} disconnected: {e.code}")
    except Exception as e:
        logger.error(f"Error handling client {client_addr}: {e}", exc_info=True)
    finally:
        session.stop()
        logger.info(f"🔌 Cleaned up session for {client_addr}")


async def main():
    health_thread = threading.Thread(target=run_health_check_server, daemon=True)
    health_thread.start()
    
    port = int(os.getenv("WS_PORT", "8765"))
    async with websockets.serve(stt_handler, "0.0.0.0", port):
        logger.info(f"🚀 RealtimeSTT WebSocket Server running on ws://0.0.0.0:{port}")
        await asyncio.Future()

if __name__ == "__main__":
    # Небольшая задержка перед стартом, чтобы дать RunPod инициализироваться
    time.sleep(3)
    asyncio.run(main())