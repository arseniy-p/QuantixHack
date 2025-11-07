#Dockerfile
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.7.19 /uv /uvx /bin/

WORKDIR /app

ENV PYTHONPATH=/app



COPY pyproject.toml .

COPY pyproject.toml README.md LICENSE* ./


RUN uv sync 

COPY . .


COPY .env .env


EXPOSE 8000

CMD ["uv", "run", "python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]