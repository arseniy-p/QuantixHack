# streamlit_app.py

import streamlit as st
import redis
import json
import time
import os
from dotenv import load_dotenv

load_dotenv()

# --- Page Configuration ---
st.set_page_config(
    page_title="Voicebot Live Dashboard",
    page_icon="🤖",
    layout="wide"
)

# --- Redis Connection ---
try:
    r = redis.Redis(
        host='localhost',
        port=6389,
        password=os.getenv('REDIS_PASSWORD'),
        decode_responses=True
    )
    r.ping()
    st.session_state.redis_connected = True
except redis.exceptions.AuthenticationError:
    st.error("Redis Authentication Failed: Please check your REDIS_PASSWORD.")
    st.session_state.redis_connected = False
except redis.exceptions.ConnectionError:
    st.error("Redis Connection Failed: Is the Redis container running and port 6379 exposed?")
    st.session_state.redis_connected = False


# --- Helper Functions ---
def display_dialog(history):
    """Renders the dialog history using chat elements."""
    for message in history:
        # Use a consistent key for chat messages
        avatar = "👤" if message["source"] == "user" else "🤖"
        with st.chat_message(message["source"], avatar=avatar):
            st.markdown(message["text"])

def get_latest_call_id():
    """Fetches the latest call ID from Redis."""
    if st.session_state.redis_connected:
        return r.get("latest_call_id")
    return None

# --- Main App Logic ---
st.title("🤖 Voicebot Live Call Dashboard")

# Initialize session state
if 'live_transcript' not in st.session_state:
    st.session_state.live_transcript = None
if 'dialog_history' not in st.session_state:
    st.session_state.dialog_history = []
if 'current_entities' not in st.session_state:
    st.session_state.current_entities = {}
if 'watching_call_id' not in st.session_state:
    st.session_state.watching_call_id = None


if not st.session_state.redis_connected:
    st.stop()

# --- Layout for the Dashboard ---
status_placeholder = st.empty()
dialog_col, state_col = st.columns([2, 1])

with dialog_col:
    dialog_placeholder = st.empty()
with state_col:
    st.subheader("Extracted State")
    state_placeholder = st.empty()



# --- Real-time Update Loop ---
# Subscribe to a pubsub channel
pubsub = r.pubsub(ignore_subscribe_messages=True)

while True:
    latest_call_id = get_latest_call_id()

    if not latest_call_id:
        status_placeholder.warning("Waiting for a new call to start...")
        time.sleep(2)
        continue

    if st.session_state.watching_call_id != latest_call_id:
        if st.session_state.watching_call_id:
            pubsub.unsubscribe()
        st.session_state.watching_call_id = latest_call_id
        st.session_state.dialog_history = []
        st.session_state.current_entities = {}
        st.session_state.live_transcript = None # Сбрасываем при новом звонке
        channel = f"call_state:{latest_call_id}"
        pubsub.subscribe(channel)
        status_placeholder.success(f"Monitoring new call: `{latest_call_id}`")

    message = pubsub.get_message()
    if message:
        data = json.loads(message['data'])
        
        if data['type'] == 'transcript':
            st.session_state.dialog_history.append(data)
            if data['source'] == 'user':
                st.session_state.live_transcript = None
        elif data['type'] == 'state_update':
            st.session_state.current_entities.update(data.get('entities', {}))
        elif data['type'] == 'interim_transcript':
            st.session_state.live_transcript = data

    with dialog_placeholder.container():
        st.subheader("Dialog Transcript")
        display_dialog(st.session_state.dialog_history)
        if st.session_state.live_transcript:
            live_data = st.session_state.live_transcript
            with st.chat_message(live_data["source"], avatar="👤"):
                st.markdown(live_data["text"] + " ▌")

    with state_placeholder.container():
        st.json(st.session_state.current_entities)
    
    time.sleep(0.05)