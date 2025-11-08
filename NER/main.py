# filename: main.py

import asyncio
import json
import websockets
from typing import Dict

# --- Import functions from your existing modules ---
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)


# Assuming they are all in the same directory
from ellabs.websocket import (
    ELEVENLABS_API_KEY, VOICE_ID, MODEL_ID, OUTPUT_FORMAT,
    receive_and_play_audio, log_with_timestamp
)
from generator.llm_generator import stream_llm_response
from ner_agent import (
    setup_nlp_rules, ConversationState, formulate_search_query, query_claims_api
)

# --------------------------------------------------------------------------
# 1. THE STREAMING ORCHESTRATOR
# --------------------------------------------------------------------------
async def stream_llm_to_tts(context_packet: Dict):
    """
    Orchestrates the entire streaming pipeline:
    1. Starts the LLM response stream.
    2. Connects to the TTS WebSocket.
    3. Streams text chunks from the LLM to the TTS service as they arrive.
    4. Concurrently receives and plays the resulting audio.
    """
    if not ELEVENLABS_API_KEY:
        print("[MAIN_ERROR] ElevenLabs API key not set.")
        return

    text_queue = asyncio.Queue()
    uri = f"wss://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/stream-input?model_id={MODEL_ID}&output_format={OUTPUT_FORMAT}"

    try:
        async with websockets.connect(uri) as websocket:
            # Task 1: The "Receiver" - Listens for and plays audio from ElevenLabs
            audio_receiver_task = asyncio.create_task(
                receive_and_play_audio(websocket)
            )

            # Task 2: The "Producer" - Gets text chunks from the LLM
            llm_producer_task = asyncio.create_task(
                stream_llm_response(context_packet, text_queue)
            )

            # Send the initial BOS (Beginning of Stream) message to ElevenLabs
            await websocket.send(json.dumps({
                "text": " ",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
                "xi_api_key": ELEVENLABS_API_KEY,
            }))

            # Task 3: The "Consumer" - Forwards text from the queue to ElevenLabs
            # This loop runs in the main coroutine
            while True:
                text_chunk = await text_queue.get()
                if text_chunk is None:  # End-of-stream signal from LLM
                    break
                await websocket.send(json.dumps({
                    "text": text_chunk,
                    "try_trigger_generation": True
                }))

            # Send the EOS (End of Stream) message to ElevenLabs
            await websocket.send(json.dumps({"text": ""}))

            # Wait for both the LLM stream and audio playback to complete
            await llm_producer_task
            await audio_receiver_task

    except Exception as e:
        log_with_timestamp(f"An error occurred in the main streaming orchestrator: {e}")

# --------------------------------------------------------------------------
# 2. THE MAIN APPLICATION LOOP
# --------------------------------------------------------------------------
async def main_conversation_loop():
    """
    The primary loop that handles user interaction, state, and calls the orchestrator.
    """
    nlp = setup_nlp_rules()
    state = ConversationState()
    print("\n--- Master Claims Agent (Streaming Voice) ---")
    print("Enter your query, or type 'quit' to exit.")

    while True:
        if state.resolved_claim:
            print(f"\n[Context: Locked on Policy ID {state.resolved_claim.get('policy_id', 'N/A')}]")
        
        # Use asyncio-friendly input to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        user_input = await loop.run_in_executor(None, input, "> ")

        if user_input.lower() in ["quit", "exit"]:
            break
        if user_input.lower() in ["clear", "reset"]:
            state.clear()
            print("[Context Cleared]")
            continue

        # 1. NER: Formulate a search query from user input
        search_query_string = formulate_search_query(user_input, nlp, state.resolved_claim)
        
        if not search_query_string.strip():
            print("[BOT]: I'm sorry, I didn't understand. Could you please rephrase?")
            # NOTE: We could add a TTS call here for simple, non-LLM responses
            continue

        # 2. API Call: Query the database/API with the extracted info
        api_result = await query_claims_api(search_query_string)
        
        # --- Handle Lock-On Logic ---
        # If no claim is locked, but we get a single result, lock onto it.
        if not state.resolved_claim and api_result['count'] == 1:
            state.resolve_to_claim(api_result['results'][0])
            log_with_timestamp(f"Context locked on Policy ID: {state.resolved_claim['policy_id']}")

        # 3. LLM & TTS: Build the context packet and stream the response
        context_packet = {
            'original_text': user_input,
            'entities': search_query_string, # Simplified for this example
            'api_results': api_result['results'],
            'locked_on_claim': state.resolved_claim
        }
        
        await stream_llm_to_tts(context_packet)

# --------------------------------------------------------------------------
# 3. SCRIPT ENTRY POINT
# --------------------------------------------------------------------------
if __name__ == "__main__":
    # Ensure you have your .env file with OPENAI_API_KEY and ELEVENLABS_API_KEY
    try:
        asyncio.run(main_conversation_loop())
    except KeyboardInterrupt:
        print("\nExiting application.")