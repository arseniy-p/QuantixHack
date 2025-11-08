# filename: llm_generator.py

import os
import json
import asyncio
from openai import AsyncOpenAI # CHANGED: Import the new AsyncOpenAI client

# --- LLM Configuration ---
# NEW: Instantiate the client with the API key.
# The client automatically reads the OPENAI_API_KEY environment variable.
client = AsyncOpenAI()
LLM_MODEL = "gpt-4" # Or "gpt-3.5-turbo" for faster, less expensive responses

# --- THIS IS THE SECTION YOU WILL EDIT FOR PROMPT ENGINEERING ---
SYSTEM_PROMPT = """
You are a friendly and professional insurance claims assistant.
Your role is to respond to the user based ONLY on the structured data provided in the user's message.

- If a single claim is found, confirm it using the customer's name and Policy ID, then ask how you can help.
- If multiple claims are found, state the number of claims and ask the user to clarify by providing a Policy ID. Do not list the claims unless the user asks.
- If no claims are found, politely state that and suggest they rephrase their search.
- If the user asks a follow-up question about a claim they are "locked on" to, use the search results to answer.
- NEVER invent information. If the data is not in the 'Database Search Results', say you do not have that information.
- Keep your responses concise and natural.
"""

def build_user_prompt(context_packet: dict) -> str:
    """Builds the user-facing prompt with all the structured data for the LLM."""

    # Check if the user is already focused on a specific claim
    if context_packet.get('locked_on_claim'):
        context_header = f"The user is asking a follow-up question about Policy ID {context_packet['locked_on_claim'].get('policy_id')}."
    else:
        context_header = "The user is performing an initial search for a claim."

    return f"""
    {context_header}

    Here is the data you must use to formulate your response:

    Original user query: "{context_packet.get('original_text', '')}"
    Extracted Information from Query: {json.dumps(context_packet.get('entities'), indent=2)}
    Database Search Results: {json.dumps(context_packet.get('api_results'), indent=2)}
    """

async def stream_llm_response(context_packet: dict, text_queue: asyncio.Queue):
    """
    Generates a response from the LLM and streams it word-by-word into a text queue.
    """
    # CHANGED: The client now holds the API key, so we check it this way.
    if not client.api_key:
        await text_queue.put("Error: OpenAI API key not configured.")
        await text_queue.put(None) # End stream
        return

    user_prompt = build_user_prompt(context_packet)

    print("\n--- Sending to LLM ---")
    print(f"System Prompt: {SYSTEM_PROMPT[:150]}...") # Print snippet
    print(f"User Prompt: {user_prompt[:200]}...")     # Print snippet
    print("-----------------------\n[BOT]: ", end="", flush=True)

    try:
        # CHANGED: The API call now uses the client instance and a new method path.
        response_stream = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            stream=True # This is the key to enabling streaming
        )

        # Asynchronously iterate over the stream of response chunks
        async for chunk in response_stream:
            # CHANGED: The way to access the text chunk is simpler now.
            text_chunk = chunk.choices[0].delta.content
            if text_chunk:
                print(text_chunk, end="", flush=True) # Print to console in real-time
                await text_queue.put(text_chunk)

    except Exception as e:
        error_message = f"[LLM_ERROR] An error occurred: {e}"
        print(error_message)
        await text_queue.put(error_message)
    finally:
        print("\n") # Newline after the full response is printed
        await text_queue.put(None) # NEW: Ensure the stream is always terminated.