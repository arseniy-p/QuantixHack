# Real-Time AI Voice Agent for Insurance Claims

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python)![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi)![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker)![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql)

This project is a fully-featured, real-time AI voice assistant named **Eva**, designed to handle user inquiries about the status of their insurance claims over a standard phone call. Users can dial a dedicated phone number, and Eva will engage in a natural language conversation to help them find information regarding their claims.

The project serves as a robust template for building modern voicebots, combining an asynchronous architecture, best-in-class cloud AI services, and reliable state management.

## Core Features

*   **Real-Time Conversation:** Low-latency audio stream processing using **Deepgram Nova-2**.
*   **Conversational AI:** A "live" and proactive assistant, "Eva," powered by **OpenAI GPT-4 Turbo**, which maintains conversational context and asks clarifying questions.
*   **Natural Language Understanding (NLU):** A two-stage system for intent and entity recognition (NER) to reliably understand user requests.
*   **Dynamic Database Search:** Full-text search capabilities over a **PostgreSQL** database to instantly retrieve relevant insurance claims.
*   **Human-like Speech:** Low-latency, natural-sounding speech synthesis using **ElevenLabs**.
*   **Live Dashboard:** An interactive **Streamlit** dashboard for real-time monitoring of calls, transcriptions, and extracted data via **Redis Pub/Sub**.
*   **Robust Architecture:** The entire system is containerized using **Docker** and orchestrated with `docker-compose` for easy deployment and scalability.

## ⚙️ System Architecture

The system is built on a modular, asynchronous architecture where a central FastAPI backend orchestrates the interaction between various services.

1.  **Telephony (Telnyx):** Receives the incoming phone call and streams audio in real-time to our backend via WebSocket.
2.  **Backend (FastAPI):**
    *   Accepts the audio stream from Telnyx.
    *   Forwards the audio to Deepgram for transcription.
    *   Receives the transcribed text from Deepgram and passes it to the `AgentService`.
3.  **STT (Deepgram):** Transcribes the audio stream and performs endpointing to detect the end of a user's utterance, returning the final text.
4.  **Agent Service (Eva's Logic):**
    *   **State & Memory Management:** Tracks the agent's state (`LISTENING`/`SPEAKING`) and stores the dialogue history for each call.
    *   **NLU/NER (GPT-3.5):** Extracts the user's `intent` and `entities` (e.g., policy number) from the transcribed text.
    *   **Retrieval:** Uses the extracted entities to perform a search against the **PostgreSQL** database.
    *   **Generation (GPT-4):** Formulates Eva's "personality" and response by feeding the entire dialogue history, database search results, and her character definition (system prompt) to the model.
5.  **TTS (ElevenLabs):** Receives text sentences from the agent, synthesizes them into audio, and streams the audio back to the backend.
6.  **Backend (FastAPI):** Receives the synthesized audio from ElevenLabs and forwards it to the user through the same Telnyx WebSocket.
7.  **Live Monitoring (Streamlit + Redis):** At each stage of the conversation (transcription, entity extraction, bot response), the backend publishes events to a **Redis** channel, which are immediately displayed on the Streamlit dashboard.

## 🛠 Tech Stack

*   **Backend:** Python, FastAPI, Uvicorn
*   **Databases:** PostgreSQL (for application data), Redis (for Pub/Sub and caching)
*   **AI & ML:**
    *   **STT:** Deepgram (Nova-2)
    *   **NLU/LLM:** OpenAI (GPT-3.5 Turbo & GPT-4 Turbo)
    *   **TTS:** ElevenLabs
*   **Telephony:** Telnyx
*   **Orchestration & Deployment:** Docker, Docker Compose
*   **Tooling:** Alembic (database migrations), SQLAlchemy (ORM), Streamlit (dashboard)

## 🚀 Getting Started

### Prerequisites

*   Docker and Docker Compose
*   Python 3.11+ and `pip` (for running Streamlit locally)
*   Accounts and API keys for:
    *   Telnyx
    *   Deepgram
    *   OpenAI
    *   ElevenLabs
*   A publicly accessible IP address or domain (you can use `ngrok` or `DuckDNS` for local development to allow Telnyx to send webhooks).

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd <your-repo-name>
```

### 2. Configuration

Create a `.env` file in the project root. You can copy `env.example` if it exists or create it from scratch. Fill in all the required variables:

```env
# PostgreSQL
POSTGRES_USER=your_db_user
POSTGRES_PASSWORD=your_db_password
POSTGRES_DB=voicebot_db
POSTGRES_HOST=postgres-voicebot-svc # Keep this for Docker networking
POSTGRES_PORT=5432

# Redis
REDIS_PASSWORD=your_redis_password

# Telnyx
TELNYX_API_KEY=your_telnyx_api_key

# AI Services
DEEPGRAM_API_KEY=your_deepgram_api_key
OPENAI_API_KEY=your_openai_api_key
ELEVENLABS_API_KEY=your_elevenlabs_api_key

# Webhook Host
# Your public domain/address WITHOUT https://
PUBLIC_HOST=your-public-domain.com
LETSENCRYPT_EMAIL=your-email@example.com
```

### 3. Telnyx Setup

1.  Purchase a phone number in your Telnyx Mission Control Portal.
2.  Create a "Call Control Application".
3.  In the application's settings, set the "Webhook URL" to `https://<YOUR_PUBLIC_HOST>/webhook/voice`.
4.  Assign your purchased phone number to this application.

### 4. Build and Run the Containers

From the project root, run:
```bash
docker-compose up --build -d
```

### 5. Database Migration and Seeding

1.  **Apply database migrations:**
    ```bash
    docker-compose run --rm migrations-voicebot-svc uv run alembic upgrade head
    ```

2.  **Seed the database with test data:**
    ```bash
    docker-compose run --rm backend-voicebot-svc python seed_db.py
    ```

### 6. Launch the Live Dashboard

In a new terminal, run the Streamlit application:

```bash
# Ensure you are in a virtual environment with the project dependencies installed
streamlit run streamlit_app.py
```

Open `http://localhost:8501` in your web browser.

### 7. Test the System

Call your Telnyx phone number. The Streamlit dashboard should show a new call and begin displaying the live conversation transcript.

## 📂 Project Structure

```
.
├── alembic/              # Database migrations
├── app/                  # Main FastAPI application source code
│   ├── agent_service.py  # "Eva" AI agent logic
│   ├── call_processor.py # Audio processing and STT handling
│   ├── crud.py           # Database access functions
│   ├── main.py           # FastAPI app, webhooks, and endpoints
│   ├── models.py         # SQLAlchemy models
│   ├── schemas.py        # Pydantic schemas
│   └── tts_service.py    # ElevenLabs TTS integration
├── docker-compose.yml    # Container orchestration
├── Dockerfile            # Instructions for building the backend image
├── pyproject.toml        # Project dependencies
├── seed_db.py            # Script to populate the database
└── streamlit_app.py      # Live monitoring dashboard code
```

## 📈 Potential Improvements (Roadmap)

*   **Advanced Barge-in Handling:** Implement more sophisticated logic to allow users to interrupt Eva gracefully, and for Eva to stop speaking and listen.
*   **User Authentication:** Use the caller's phone number (`from_number`) to automatically identify them in the database.
*   **Scalable State Management:** Migrate dialogue history and agent states from in-memory dictionaries to Redis to better support multiple concurrent calls.
*   **Custom STT Worker:** Finalize the integration with the `RealtimeSTT` worker on RunPod for full control over the speech-to-text pipeline.
*   **CI/CD:** Set up a continuous integration and deployment pipeline to automate building, testing, and deploying code changes.
