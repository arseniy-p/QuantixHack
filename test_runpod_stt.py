#!/usr/bin/env python3
"""
Тестовый скрипт для проверки RunPod STT WebSocket сервера.
Поддерживает несколько режимов тестирования:
1. Тишина (проверка базовой работы)
2. Синтетическая речь (тон на определенной частоте)
3. Реальное аудио из файла
"""

import asyncio
import websockets
import json
import numpy as np
import argparse
import sys
from pathlib import Path
from typing import Optional
import wave

class Colors:
    """ANSI цвета для красивого вывода"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'

def print_color(text: str, color: str = Colors.END):
    """Печать цветного текста"""
    print(f"{color}{text}{Colors.END}")

def generate_silence(duration_sec: float, sample_rate: int = 16000) -> bytes:
    """Генерирует тишину"""
    samples = int(duration_sec * sample_rate)
    audio = np.zeros(samples, dtype=np.int16)
    return audio.tobytes()

def generate_tone(duration_sec: float, frequency: int = 440, sample_rate: int = 16000) -> bytes:
    """Генерирует синусоидальный тон (имитация голоса)"""
    samples = int(duration_sec * sample_rate)
    t = np.linspace(0, duration_sec, samples, False)
    
    # Синусоида с амплитудной модуляцией (похоже на речь)
    carrier = np.sin(2 * np.pi * frequency * t)
    modulation = 0.5 * np.sin(2 * np.pi * 3 * t) + 0.5  # 3 Hz модуляция
    audio = (carrier * modulation * 10000).astype(np.int16)
    
    return audio.tobytes()

def load_audio_file(filepath: Path, target_sample_rate: int = 16000) -> Optional[bytes]:
    """Загружает аудио из WAV файла и конвертирует в 16kHz mono PCM"""
    try:
        with wave.open(str(filepath), 'rb') as wav:
            channels = wav.getnchannels()
            sample_rate = wav.getframerate()
            sample_width = wav.getsampwidth()
            audio_data = wav.readframes(wav.getnframes())
            
        print_color(f"📁 Loaded: {channels}ch, {sample_rate}Hz, {sample_width*8}bit", Colors.CYAN)
        
        # Конвертация в numpy
        audio_np = np.frombuffer(audio_data, dtype=np.int16)
        
        # Если стерео - берем один канал
        if channels == 2:
            audio_np = audio_np[::2]
            
        # Ресемплинг если нужно (простой, без библиотек)
        if sample_rate != target_sample_rate:
            ratio = target_sample_rate / sample_rate
            new_length = int(len(audio_np) * ratio)
            audio_np = np.interp(
                np.linspace(0, len(audio_np), new_length),
                np.arange(len(audio_np)),
                audio_np
            ).astype(np.int16)
            
        return audio_np.tobytes()
        
    except Exception as e:
        print_color(f"❌ Error loading audio: {e}", Colors.RED)
        return None

async def test_websocket(
    ws_url: str,
    audio_data: bytes,
    chunk_duration_ms: int = 20,
    sample_rate: int = 16000
):
    """
    Основная функция тестирования WebSocket
    
    Args:
        ws_url: URL WebSocket сервера
        audio_data: Аудио данные для отправки
        chunk_duration_ms: Размер чанка в миллисекундах
        sample_rate: Частота дискретизации
    """
    print_color("\n" + "="*60, Colors.HEADER)
    print_color("🚀 Starting WebSocket Test", Colors.HEADER)
    print_color("="*60, Colors.HEADER)
    
    chunk_size = int(sample_rate * chunk_duration_ms / 1000) * 2  # *2 для int16
    total_duration = len(audio_data) / (sample_rate * 2)
    
    print_color(f"\n📊 Test Parameters:", Colors.BLUE)
    print(f"   URL: {ws_url}")
    print(f"   Audio duration: {total_duration:.2f}s")
    print(f"   Chunk size: {chunk_duration_ms}ms ({chunk_size} bytes)")
    print(f"   Sample rate: {sample_rate}Hz")
    
    try:
        print_color(f"\n🔌 Connecting to {ws_url}...", Colors.YELLOW)
        
        async with websockets.connect(ws_url, ping_interval=30) as ws:
            print_color("✅ Connected!", Colors.GREEN)
            
            # Задача для получения сообщений
            async def receive_messages():
                interim_count = 0
                final_count = 0
                
                try:
                    async for message in ws:
                        data = json.loads(message)
                        msg_type = data.get("type", "unknown")
                        
                        if msg_type == "ready":
                            print_color(f"\n✅ Server Ready:", Colors.GREEN)
                            print(f"   Model: {data.get('model')}")
                            print(f"   Realtime: {data.get('realtime_model')}")
                            if 'device' in data:
                                print(f"   Device: {data.get('device')}")
                            
                        elif msg_type == "interim_transcript":
                            interim_count += 1
                            text = data.get("text", "")
                            print_color(f"💬 Interim #{interim_count}: {text}", Colors.CYAN)
                            
                        elif msg_type == "transcript":
                            final_count += 1
                            text = data.get("text", "")
                            duration = data.get("duration", 0)
                            print_color(f"\n📝 Final #{final_count}: {text}", Colors.GREEN + Colors.BOLD)
                            if duration:
                                print(f"   Duration: {duration:.2f}s")
                        
                        else:
                            print_color(f"❓ Unknown message type: {msg_type}", Colors.YELLOW)
                            print(f"   Data: {data}")
                            
                except websockets.exceptions.ConnectionClosed:
                    print_color("\n🔌 Connection closed by server", Colors.YELLOW)
                except Exception as e:
                    print_color(f"\n❌ Error receiving messages: {e}", Colors.RED)
            
            # Запускаем задачу получения сообщений
            receive_task = asyncio.create_task(receive_messages())
            
            # Отправляем аудио чанками
            print_color(f"\n📤 Sending audio data...", Colors.BLUE)
            chunks_sent = 0
            
            for i in range(0, len(audio_data), chunk_size):
                chunk = audio_data[i:i+chunk_size]
                await ws.send(chunk)
                chunks_sent += 1
                
                # Прогресс
                if chunks_sent % 50 == 0:
                    progress = (i / len(audio_data)) * 100
                    print(f"   Progress: {progress:.1f}% ({chunks_sent} chunks)", end='\r')
                
                # Симулируем реальное время (20ms между чанками)
                await asyncio.sleep(chunk_duration_ms / 1000)
            
            print(f"\n✅ Sent {chunks_sent} chunks ({total_duration:.2f}s of audio)")
            
            # Ждем еще немного для получения финальных транскрипций
            print_color("\n⏳ Waiting for final transcriptions...", Colors.YELLOW)
            await asyncio.sleep(3)
            
            # Закрываем соединение
            await ws.close()
            receive_task.cancel()
            
            print_color("\n✅ Test completed successfully!", Colors.GREEN + Colors.BOLD)
            
    except websockets.exceptions.WebSocketException as e:
        print_color(f"\n❌ WebSocket error: {e}", Colors.RED)
        return False
    except Exception as e:
        print_color(f"\n❌ Unexpected error: {e}", Colors.RED)
        import traceback
        traceback.print_exc()
        return False
    
    return True

async def run_test(args):
    """Запуск теста с выбранным типом аудио"""
    
    # Генерируем или загружаем аудио
    if args.mode == "silence":
        print_color("🔇 Generating silence test...", Colors.CYAN)
        audio_data = generate_silence(args.duration)
        
    elif args.mode == "tone":
        print_color(f"🎵 Generating tone test ({args.frequency}Hz)...", Colors.CYAN)
        audio_data = generate_tone(args.duration, args.frequency)
        
    elif args.mode == "file":
        if not args.file:
            print_color("❌ Error: --file required for 'file' mode", Colors.RED)
            return False
            
        audio_path = Path(args.file)
        if not audio_path.exists():
            print_color(f"❌ Error: File not found: {audio_path}", Colors.RED)
            return False
            
        print_color(f"📁 Loading audio from {audio_path}...", Colors.CYAN)
        audio_data = load_audio_file(audio_path)
        if audio_data is None:
            return False
    
    else:
        print_color(f"❌ Unknown mode: {args.mode}", Colors.RED)
        return False
    
    # Запускаем тест
    return await test_websocket(args.url, audio_data)

def main():
    parser = argparse.ArgumentParser(
        description="Test RunPod STT WebSocket Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with silence (check basic connectivity)
  python test_runpod_stt.py ws://localhost:8765
  
  # Test with synthetic tone (simulates voice)
  python test_runpod_stt.py ws://your-pod.runpod.net:12345 --mode tone --duration 3
  
  # Test with real audio file
  python test_runpod_stt.py ws://your-pod.runpod.net:12345 --mode file --file audio.wav
        """
    )
    
    parser.add_argument(
        "url",
        help="WebSocket URL (e.g., ws://213.173.108.16:18713)"
    )
    
    parser.add_argument(
        "--mode",
        choices=["silence", "tone", "file"],
        default="tone",
        help="Test mode (default: tone)"
    )
    
    parser.add_argument(
        "--duration",
        type=float,
        default=2.0,
        help="Duration in seconds for silence/tone modes (default: 2.0)"
    )
    
    parser.add_argument(
        "--frequency",
        type=int,
        default=440,
        help="Frequency in Hz for tone mode (default: 440)"
    )
    
    parser.add_argument(
        "--file",
        type=str,
        help="Audio file path for file mode (WAV format)"
    )
    
    args = parser.parse_args()
    
    # Запуск теста
    try:
        success = asyncio.run(run_test(args))
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print_color("\n\n⚠️  Test interrupted by user", Colors.YELLOW)
        sys.exit(1)

if __name__ == "__main__":
    main()