# runpod_stt_worker/stt_server.py (ПРАВИЛЬНАЯ ВЕРСИЯ с RealtimeSTT)

import asyncio
import websockets
import json
import os
import logging
from RealtimeSTT import AudioToTextRecorder
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from queue import Queue
import time

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - [%(levelname)s] - %(message)s",
)
logger = logging.getLogger(__name__)

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass

def run_health_check_server():
    server_address = ('', 8080)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    logger.info("Health check server running on port 8080...")
    httpd.serve_forever()


class RealtimeSTTSession:
    """
    Обертка для одной сессии транскрипции.
    Использует глобальный recorder, но управляет состоянием индивидуально.
    """
    
    def __init__(self, websocket, recorder):
        self.websocket = websocket
        self.recorder = recorder
        self.is_active = True
        self.last_transcript = ""
        self.transcript_lock = threading.Lock()
        
    def on_transcription(self, text):
        """Callback для финальных транскрипций"""
        if not self.is_active:
            return
            
        text = text.strip()
        if not text:
            return
            
        logger.info(f"📝 Final transcript: '{text}'")
        
        # Отправляем асинхронно
        asyncio.create_task(self._send_transcript(text, is_final=True))
    
    def on_realtime_update(self, text):
        """Callback для промежуточных транскрипций"""
        if not self.is_active:
            return
            
        text = text.strip()
        
        # Отправляем только если текст изменился
        with self.transcript_lock:
            if text and text != self.last_transcript:
                self.last_transcript = text
                asyncio.create_task(self._send_transcript(text, is_final=False))
    
    async def _send_transcript(self, text, is_final):
        """Отправка транскрипции клиенту"""
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
        """Передача аудио в recorder"""
        if self.is_active:
            try:
                self.recorder.feed_audio(audio_chunk)
            except Exception as e:
                logger.error(f"Error feeding audio: {e}")
    
    def stop(self):
        """Остановка сессии"""
        self.is_active = False
        with self.transcript_lock:
            self.last_transcript = ""


class GlobalRecorderManager:
    """
    Менеджер глобального recorder'а.
    Создает один recorder при старте и переиспользует его для всех соединений.
    """
    
    def __init__(self):
        self.recorder = None
        self.lock = threading.Lock()
        self._initialize_recorder()
    
    def _initialize_recorder(self):
        """Инициализация и прогрев модели"""
        logger.info("🔥 Initializing RealtimeSTT recorder (this may take a minute)...")
        
        model_size = os.getenv("MODEL_SIZE", "medium.en")
        
        try:
            self.recorder = AudioToTextRecorder(
                model=model_size,
                language="en",
                device="cuda",
                gpu_device_index=0,
                compute_type="float16",
                use_microphone=False,  # ВАЖНО: не используем микрофон
                spinner=False,
                
                # Параметры для реалтайм транскрипции
                enable_realtime_transcription=True,
                realtime_model_type="tiny.en",  # Быстрая модель для промежуточных результатов
                realtime_processing_pause=0.1,  # Обновление каждые 100ms
                
                # VAD настройки
                silero_sensitivity=0.4,
                silero_use_onnx=True,
                silero_deactivity_detection=True,
                webrtc_sensitivity=3,
                
                # Тайминги
                post_speech_silence_duration=0.7,  # 700ms тишины = конец фразы
                min_length_of_recording=0.5,
                min_gap_between_recordings=0.3,
                pre_recording_buffer_duration=0.3,
                
                # Производительность
                beam_size=5,
                beam_size_realtime=3,
                
                # Логирование
                level=logging.INFO,
                no_log_file=True,
            )
            
            logger.info("✅ RealtimeSTT recorder initialized successfully")
            
            # Прогрев модели тестовым аудио (1 секунда тишины)
            logger.info("🔥 Warming up model with test audio...")
            import numpy as np
            warmup_audio = np.zeros(16000, dtype=np.int16).tobytes()
            self.recorder.feed_audio(warmup_audio)
            time.sleep(2)
            logger.info("✅ Model warmed up and ready")
            
        except Exception as e:
            logger.error(f"Failed to initialize recorder: {e}", exc_info=True)
            raise
    
    def create_session(self, websocket):
        """Создает новую сессию для клиента"""
        with self.lock:
            return RealtimeSTTSession(websocket, self.recorder)


# Глобальный менеджер (создается один раз при старте)
recorder_manager = None


async def stt_handler(websocket):
    """Обработчик WebSocket соединений"""
    client_addr = websocket.remote_address
    logger.info(f"🔌 Client connected from {client_addr}")
    
    session = None
    
    try:
        # Создаем сессию для этого клиента
        session = recorder_manager.create_session(websocket)
        
        # Устанавливаем callbacks для этой сессии
        session.recorder.on_transcription_finished = session.on_transcription
        session.recorder.on_realtime_transcription_update = session.on_realtime_update
        
        # Отправляем подтверждение готовности
        model_info = {
            "type": "ready",
            "model": os.getenv("MODEL_SIZE", "medium.en"),
            "realtime_model": "tiny.en"
        }
        await websocket.send(json.dumps(model_info))
        logger.info(f"✅ Session ready for {client_addr}")
        
        # Обрабатываем входящие аудио чанки
        async for message in websocket:
            if isinstance(message, bytes):
                # Передаем аудио в recorder
                session.feed_audio(message)
            else:
                logger.warning(f"Received non-binary message: {message[:100]}")
        
        logger.info(f"Client {client_addr} closed connection normally")
        
    except websockets.exceptions.ConnectionClosed as e:
        logger.info(f"Client {client_addr} disconnected: {e.code} - {e.reason}")
    except Exception as e:
        logger.error(f"Error handling client {client_addr}: {e}", exc_info=True)
        try:
            await websocket.close(1011, f"Server error: {str(e)[:100]}")
        except:
            pass
    finally:
        # Останавливаем сессию
        if session:
            session.stop()
        logger.info(f"🔌 Cleaned up session for {client_addr}")


async def main():
    """Запуск серверов"""
    global recorder_manager
    
    # Диагностика окружения
    logger.info("=" * 60)
    logger.info("System Diagnostics")
    logger.info("=" * 60)
    
    try:
        import torch
        logger.info(f"PyTorch version: {torch.__version__}")
        logger.info(f"CUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            logger.info(f"CUDA version: {torch.version.cuda}")
            logger.info(f"GPU: {torch.cuda.get_device_name(0)}")
    except Exception as e:
        logger.error(f"Error checking PyTorch: {e}")
    
    try:
        import ctranslate2
        logger.info(f"ctranslate2 version: {ctranslate2.__version__}")
    except Exception as e:
        logger.error(f"Error checking ctranslate2: {e}")
    
    try:
        import subprocess
        result = subprocess.run(
            ['ldconfig', '-p'],
            capture_output=True,
            text=True,
            timeout=5
        )
        cudnn_libs = [line.strip() for line in result.stdout.split('\n') if 'cudnn' in line.lower()]
        logger.info(f"cuDNN libraries found: {len(cudnn_libs)}")
        for lib in cudnn_libs[:5]:  # Показываем первые 5
            logger.info(f"  {lib}")
    except Exception as e:
        logger.warning(f"Could not check cuDNN libraries: {e}")
    
    logger.info("=" * 60)
    
    # Инициализируем глобальный recorder
    recorder_manager = GlobalRecorderManager()
    
    # Health check в отдельном потоке
    health_thread = threading.Thread(target=run_health_check_server, daemon=True)
    health_thread.start()
    
    # WebSocket сервер
    port = int(os.getenv("WS_PORT", "8765"))
    
    async with websockets.serve(
        stt_handler,
        "0.0.0.0",
        port,
        ping_interval=30,
        ping_timeout=10,
        max_size=10 * 1024 * 1024  # 10MB
    ):
        logger.info(f"🚀 RealtimeSTT WebSocket Server running on ws://0.0.0.0:{port}")
        logger.info(f"📊 Model: {os.getenv('MODEL_SIZE', 'medium.en')}")
        logger.info(f"💾 Using CUDA for acceleration")
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    asyncio.run(main())