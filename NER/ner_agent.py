# filename: agent.py

import spacy
import asyncio
import aiohttp 
import regex as re

import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

from ellabs.websocket import speak_text

# --------------------------------------------------------------------------
# 0. API CONFIGURATION
# --------------------------------------------------------------------------
API_URL = "https://quantixhack.duckdns.org/claims/search"

async def query_claims_api(search_text: str):
    if not isinstance(search_text, str):
        search_text = str(search_text)
    payload = {"text": search_text}
    print(f"  -> Sending JSON to API: {payload}")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(API_URL, json=payload, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    return {'count': len(data), 'results': data, 'error': None}
                else:
                    error_text = await response.text()
                    return {'count': 0, 'results': [], 'error': f"API Error (Status {response.status}): {error_text}"}
        except aiohttp.ClientError as e:
            return {'count': 0, 'results': [], 'error': f"Connection Error: {e}"}
        except asyncio.TimeoutError:
            return {'count': 0, 'results': [], 'error': "Connection timed out."}

# --------------------------------------------------------------------------
# 1. SETUP & STATE (No changes needed here)
# --------------------------------------------------------------------------
def setup_nlp_rules():
    print("Loading NLP model for API keyword extraction...")
    nlp = spacy.load("en_core_web_lg")
    print("Model ready.")
    return nlp

class ConversationState:
    def __init__(self):
        self.resolved_claim = None
    def resolve_to_claim(self, claim_record):
        self.resolved_claim = claim_record
    def clear(self):
        self.resolved_claim = None

# --------------------------------------------------------------------------
# 3. NLU ENGINE (No changes needed here)
# --------------------------------------------------------------------------
def formulate_search_query(text: str, nlp, context_claim=None) -> str:
    if context_claim and 'policy_id' in context_claim:
        return f"{context_claim['policy_id']} {text}"
    doc = nlp(text)
    search_terms = []
    for ent in doc.ents:
        if ent.label_ in ["PERSON", "DATE", "ORG", "GPE", "PRODUCT"]:
            search_terms.append(ent.text)
    for chunk in doc.noun_chunks:
        if chunk.root.ent_type_ == 0:
             search_terms.append(chunk.text)
    policy_id_match = re.search(r'POL-\d{3,}', text, re.IGNORECASE)
    if policy_id_match:
        search_terms.append(policy_id_match.group(0))
    unique_terms = list(dict.fromkeys(search_terms))
    final_query = " ".join(unique_terms)
    if not final_query.strip():
        return text
    return final_query

# --------------------------------------------------------------------------
# 4. MAIN AGENT LOOP (MODIFIED FOR VOICE OUTPUT)
# --------------------------------------------------------------------------
async def start_interactive_session():
    nlp = setup_nlp_rules()
    state = ConversationState()
    print("\n--- Master Claims Agent (Voice Enabled) ---")
    
    while True:
        if state.resolved_claim:
            print(f"[Context: Locked on Policy ID {state.resolved_claim.get('policy_id', 'N/A')}]")
        
        # Use asyncio-friendly input to avoid blocking
        loop = asyncio.get_running_loop()
        user_input = await loop.run_in_executor(None, input, "> ")

        if user_input.lower() in ["quit", "exit"]: break
        if user_input.lower() in ["clear", "reset"]:
            state.clear(); print("[Context Cleared]"); continue

        search_query_string = formulate_search_query(user_input, nlp, state.resolved_claim)
        
        if not search_query_string.strip():
            bot_message = "I'm sorry, I didn't understand. Could you please rephrase?"
            print(f"[BOT]: {bot_message}")
            await speak_text(bot_message) # <-- SPEAK
            continue

        api_result = await query_claims_api(search_query_string)
        bot_message = "" # This will hold the text to be spoken

        # --- Analysis and Response ---
        if api_result['error']:
            bot_message = f"I encountered an error: {api_result['error']}"
        elif state.resolved_claim:
            if api_result['count'] > 0:
                bot_message = "Here is the latest information on that claim."
                print(f"  Result: {api_result['results'][0]}")
            else:
                bot_message = f"I couldn't find any new details for '{user_input}' regarding this claim."
        else:
            if api_result['count'] == 1:
                claim = api_result['results'][0]
                policy_id = claim.get('policy_id', 'N/A')
                customer_name = claim.get('customer_name', 'N/A')
                bot_message = f"Thank you. I've located claim {policy_id} for {customer_name}. How can I help you with it?"
                state.resolve_to_claim(claim)
            elif api_result['count'] > 1:
                bot_message = f"I found {api_result['count']} possible claims. Can you provide a Policy ID or be more specific?"
                for claim in api_result['results']:
                    print(f"  - Claim ({claim.get('policy_id', 'N/A')}): {claim.get('description', 'No description')}")
            else: # count == 0
                bot_message = "I couldn't find any claims matching that information. Please try again."

        # --- Print and Speak the final generated response ---
        if bot_message:
            print(f"[BOT]: {bot_message}")
            await speak_text(bot_message) # <-- SPEAK

if __name__ == "__main__":
    try:
        asyncio.run(start_interactive_session())
    except KeyboardInterrupt:
        print("\nExiting...")