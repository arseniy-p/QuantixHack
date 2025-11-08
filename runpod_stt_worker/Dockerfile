# runpod_stt_worker/Dockerfile (ФИНАЛЬНАЯ ВЕРСИЯ - по образцу RealtimeSTT)

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

WORKDIR /app

# Устанавливаем Python и системные зависимости
# КЛЮЧЕВОЙ МОМЕНТ: libcudnn8 вместо cudnn9!
RUN apt-get update -y && \
    apt-get install -y \
    python3.11 \
    python3.11-dev \
    python3-pip \
    libcudnn8 \
    libcudnn8-dev \
    libcublas-12-4 \
    portaudio19-dev \
    ffmpeg \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Делаем python3.11 дефолтным
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 && \
    update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

# Устанавливаем PyTorch (версия совместимая с CUDA 12.4 и cuDNN 8)
RUN pip3 install --no-cache-dir \
    torch==2.5.1 \
    torchaudio==2.5.1 \
    --index-url https://download.pytorch.org/whl/cu124

# UV для быстрой установки остальных пакетов
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/

# Создаем директорию для моделей
RUN mkdir -p /app/models

# Копируем и устанавливаем зависимости
COPY pyproject.toml .
RUN uv pip install --system -r pyproject.toml --no-cache

# Копируем код
COPY stt_server.py .

# Переменные окружения
ENV LOG_LEVEL=INFO \
    MODEL_SIZE=medium.en \
    WS_PORT=8765 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/lib/x86_64-linux-gnu

# Порты
EXPOSE 8765 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Запуск
CMD ["python3", "-u", "stt_server.py"]