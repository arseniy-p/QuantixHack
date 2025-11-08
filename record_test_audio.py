#!/usr/bin/env python3
"""
Простой скрипт для записи тестового аудио с микрофона.
Записывает 5 секунд аудио и сохраняет в test_audio.wav
"""

import pyaudio
import wave
import sys

def record_audio(filename="test_audio.wav", duration=5, sample_rate=16000):
    """Записывает аудио с микрофона"""
    
    CHUNK = 1024
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    
    print("🎤 Initializing microphone...")
    
    p = pyaudio.PyAudio()
    
    try:
        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=sample_rate,
            input=True,
            frames_per_buffer=CHUNK
        )
        
        print(f"\n🔴 Recording {duration} seconds...")
        print("   Speak now!")
        
        frames = []
        for i in range(0, int(sample_rate / CHUNK * duration)):
            data = stream.read(CHUNK)
            frames.append(data)
            
            # Прогресс
            progress = (i / (sample_rate / CHUNK * duration)) * 100
            print(f"   Progress: {progress:.1f}%", end='\r')
        
        print("\n\n✅ Recording finished!")
        
        stream.stop_stream()
        stream.close()
        
        # Сохранение
        print(f"💾 Saving to {filename}...")
        wf = wave.open(filename, 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(sample_rate)
        wf.writeframes(b''.join(frames))
        wf.close()
        
        print(f"✅ Saved to {filename}")
        print(f"\nNow you can test with:")
        print(f"  python test_runpod_stt.py ws://your-url --mode file --file {filename}")
        
    finally:
        p.terminate()

if __name__ == "__main__":
    try:
        duration = int(sys.argv[1]) if len(sys.argv) > 1 else 5
        record_audio(duration=duration)
    except KeyboardInterrupt:
        print("\n\n⚠️  Recording interrupted")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nMake sure pyaudio is installed:")
        print("  pip install pyaudio")