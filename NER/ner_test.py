import spacy
import asyncio
import aiohttp 
import regex as re # Using the 'regex' library as requested

# --------------------------------------------------------------------------
# 0. API CONFIGURATION
# --------------------------------------------------------------------------
# CORRECTED: Using https to connect to the proper API endpoint
API_URL = "https://quantixhack.duckdns.org/claims/search"

async def query_claims_api(search_text: str):
    """
    Sends a well-formed JSON payload with a single string to the API.
    """
    # Ensure search_text is a string, even if something unexpected happens.
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
# 1. SETUP: The Agent's Knowledge Base
# --------------------------------------------------------------------------
def setup_nlp_rules():
    print("Loading NLP model for API keyword extraction...")
    nlp = spacy.load("en_core_web_sm")
    print("Model ready.")
    return nlp

# --------------------------------------------------------------------------
# 2. THE AGENT'S BRAIN: State Management
# --------------------------------------------------------------------------
class ConversationState:
    def __init__(self):
        self.resolved_claim = None

    def resolve_to_claim(self, claim_record):
        self.resolved_claim = claim_record

    def clear(self):
        self.resolved_claim = None

# --------------------------------------------------------------------------
# 3. NLU ENGINE: Formulating the Search String
# --------------------------------------------------------------------------
def formulate_search_query(text: str, nlp, context_claim=None) -> str:
    """
    Extracts key entities and nouns to create a concise, single search string for the FTS API.
    """
    # If locked on a claim, use its ID as the primary search term.
    # Note: The API returns keys in lowercase, e.g., 'policy_id'.
    if context_claim and 'policy_id' in context_claim:
        return f"{context_claim['policy_id']} {text}"
        
    # If not locked on, perform NLU to find the best keywords.
    doc = nlp(text)
    search_terms = []
    
    # Extract entities (people, dates, organizations)
    for ent in doc.ents:
        if ent.label_ in ["PERSON", "DATE", "ORG", "GPE", "PRODUCT"]:
            search_terms.append(ent.text)
            
    # Extract important noun chunks (e.g., "pipe burst", "auto accident")
    for chunk in doc.noun_chunks:
        if chunk.root.ent_type_ == 0:
             search_terms.append(chunk.text)

    # Simple regex for policy IDs if spaCy misses them
    policy_id_match = re.search(r'POL-\d{3,}', text, re.IGNORECASE)
    if policy_id_match:
        search_terms.append(policy_id_match.group(0))

    # Join unique terms into a single string.
    unique_terms = list(dict.fromkeys(search_terms))
    final_query = " ".join(unique_terms)
    
    # Failsafe: if no terms were found, use the original text.
    if not final_query.strip():
        return text

    return final_query

# --------------------------------------------------------------------------
# 4. MAIN AGENT LOOP
# --------------------------------------------------------------------------
async def start_interactive_session():
    nlp = setup_nlp_rules()
    state = ConversationState()
    print("\n--- Master Claims Agent (Live API Enabled v2) ---")
    
    while True:
        if state.resolved_claim:
            # Note: The API returns keys in lowercase, e.g., 'policy_id'.
            print(f"[Context: Locked on Policy ID {state.resolved_claim.get('policy_id', 'N/A')}]")
        
        user_input = input("> ")
        if user_input.lower() in ["quit", "exit"]: break
        if user_input.lower() in ["clear", "reset"]:
            state.clear(); print("[Context Cleared]"); continue

        # --- NLU and API Call ---
        search_query_string = formulate_search_query(user_input, nlp, state.resolved_claim)
        
        if not search_query_string.strip():
            print("[BOT]: I'm sorry, I didn't understand. Could you please rephrase?")
            continue

        api_result = await query_claims_api(search_query_string)

        # --- Analysis and Response ---
        if api_result['error']:
            print(f"[BOT_ERROR]: {api_result['error']}")
            continue

        if state.resolved_claim:
            if api_result['count'] > 0:
                print("[BOT]: Here is the latest information on that claim:")
                print(f"  Result: {api_result['results'][0]}")
            else:
                print(f"[BOT]: I couldn't find any new details for '{user_input}' regarding this claim.")
        else:
            # Logic for finding and resolving a claim
            if api_result['count'] == 1:
                claim = api_result['results'][0]
                print(f"[BOT]: Thank you. I've located claim {claim.get('policy_id', 'N/A')} for {claim.get('customer_name', 'N/A')}. How can I help you with it?")
                state.resolve_to_claim(claim)
            
            elif api_result['count'] > 1:
                print(f"[BOT]: I found {api_result['count']} possible claims. Can you provide a Policy ID or be more specific?")
                for claim in api_result['results']:
                    print(f"  - Claim ({claim.get('policy_id', 'N/A')}): {claim.get('description', 'No description')}")
            
            else: # count == 0
                print("[BOT]: I couldn't find any claims matching that information. Please try again.")

if __name__ == "__main__":
    try:
        asyncio.run(start_interactive_session())
    except KeyboardInterrupt:
        print("\nExiting...")