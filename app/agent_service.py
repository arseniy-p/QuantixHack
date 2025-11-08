# filename: app/agent_service.py

import json
import asyncio
import re
from openai import AsyncOpenAI

from . import crud
from .database import SessionLocal
from .logger_config import logger
from .tts_service import stream_tts_to_telnyx

# --- Конфигурация ---
client = AsyncOpenAI() 
LLM_MODEL_NER = "gpt-3.5-turbo" 
LLM_MODEL_GEN = "gpt-4-turbo"   

# Хранилище истории звонков
call_histories = {}
call_states = {} 

# --- ШАГ 1: Улучшенный NER ---
async def extract_entities(user_utterance: str) -> dict:
    """
    Извлекает сущности с помощью LLM, обученного на примерах.
    """
    logger.info(f"Extracting entities from: '{user_utterance}'")
    
    # Regex остается как самый надежный первый фильтр
    policy_id_match = re.search(r'(POL|HPC|AUT|BUS)-\d{4}', user_utterance, re.IGNORECASE)
    if policy_id_match:
        return {"intent": "claim_status_check", "policy_id": policy_id_match.group(0).upper()}

    # Новый, более умный промпт для NER
    system_prompt = """
    You are a Named Entity Recognition (NER) engine. Your task is to analyze the user's text and return a JSON object with 'intent' and other entities.

    Possible intents:
    - "claim_status_check": If the user wants to know the status, update, or any information about their insurance claim/case/inquiry.
    - "greeting": For simple hellos and greetings.
    - "affirmative": For "yes", "yep", "correct".
    - "negative": For "no", "nope".
    - "repeat": If the user asks to repeat the last message.
    - "other": For anything else.

    Entities to extract:
    - "policy_id": (e.g., "POL-1234")
    - "keywords": (e.g., "car accident")

    Examples:
    - "Can I ask about the status of my insurance inquiry?" -> {"intent": "claim_status_check"}
    - "What's happening with my water damage case?" -> {"intent": "claim_status_check", "keywords": "water damage"}
    - "Hello there" -> {"intent": "greeting"}
    - "Yes, that's the one." -> {"intent": "affirmative"}
    """
    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL_NER,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_utterance}
            ],
            response_format={"type": "json_object"}
        )
        entities = json.loads(response.choices[0].message.content)
        logger.info(f"Entities extracted: {entities}")
        return entities
    except Exception as e:
        logger.error(f"Failed to extract entities: {e}")
        return {"intent": "error"}

# --- ШАГ 2: Новый промпт-личность для Евы ---
def build_eva_prompt(history: list, db_results: list, entities: dict) -> list:
    system_prompt = """
    You are Eva, a friendly, empathetic, and highly professional AI voice assistant from an insurance company in Portugal. Your primary goal is to help users by providing the status of their insurance claims.

    **Your Personality:**
    - **Proactive:** Your main goal is to get a Policy ID. Don't wait for it. If the user is vague, you MUST ask for the policy number.
    - **Human & Conversational:** Use natural language. Greet users warmly. Acknowledge their statements.
    - **Focused:** You have one job: check claim status. Gently guide users back if they go off-topic.

    **Your Logic Flow (Strict Rules):**
    1.  **Greeting:** If the user says hello, greet them back and immediately ask how you can help *with their claim*. Example: "Good morning! How can I help you with your insurance claim today?"
    2.  **Information Gathering:** If the intent is "claim_status_check" but there is NO policy_id, you MUST ask for it. Say: "I can certainly help with that. Could you please provide your policy number?"
    3.  **Using Data:** When `Database Search Results` are provided, you MUST use them to answer.
        - If one claim is found: "Okay, I've found the claim for policy [policy_id]. The current status is [status]."
        - If no claims are found: "I'm sorry, I couldn't find a claim matching that information. Would you like to try a different policy number?"
    4.  **Use History:** Pay attention to the full conversation history to understand context.
    """
    
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    
    context_for_llm = f"""
    --- INTERNAL CONTEXT (for your eyes only) ---
    Extracted Entities from user's last message: {json.dumps(entities)}
    Database Search Results: {json.dumps(db_results)}
    --- END INTERNAL CONTEXT ---
    Now, based on the history and the context, generate your response to the user.
    """
    messages.append({"role": "user", "content": context_for_llm})
    return messages


async def stream_llm_and_tts_eva(messages: list, websocket, call_control_id: str) -> str:
    """
    Стримит ответ от LLM, отправляет его по предложениям в TTS и возвращает полный текст.
    """
    sentence_buffer = ""
    full_response_text = ""
    sentence_enders = [".", "?", "!"]

    try:
        response_stream = await client.chat.completions.create(
            model=LLM_MODEL_GEN, messages=messages, stream=True
        )
        async for chunk in response_stream:
            text_chunk = chunk.choices[0].delta.content
            if not text_chunk: continue
            
            sentence_buffer += text_chunk
            full_response_text += text_chunk

            if any(ender in sentence_buffer for ender in sentence_enders):
                first_ender_pos = -1
                for ender in sentence_enders:
                    pos = sentence_buffer.find(ender)
                    if pos != -1 and (first_ender_pos == -1 or pos < first_ender_pos):
                        first_ender_pos = pos

                if first_ender_pos != -1:
                    sentence_to_speak = sentence_buffer[:first_ender_pos + 1]
                    sentence_buffer = sentence_buffer[first_ender_pos + 1:]
                    
                    logger.info(f"[{call_control_id}] TTS speaking sentence: '{sentence_to_speak.strip()}'")
                    asyncio.create_task(
                        stream_tts_to_telnyx(sentence_to_speak.strip(), websocket, call_control_id)
                    )
        
        if sentence_buffer.strip():
            logger.info(f"[{call_control_id}] TTS speaking final part: '{sentence_buffer.strip()}'")
            await stream_tts_to_telnyx(sentence_buffer.strip(), websocket, call_control_id)
        
        return full_response_text
        
    except Exception as e:
        logger.error(f"[{call_control_id}] Error in TTS stream: {e}", exc_info=True)
        return ""


async def handle_user_input(
    user_utterance: str,
    call_control_id: str,
    websocket,
    redis_client
):
    # 1. Проверяем состояние. Если Ева говорит, игнорируем новый транскрипт.
    if call_states.get(call_control_id) == "SPEAKING":
        logger.warning(f"[{call_control_id}] User spoke while Eva was speaking. Ignoring.")
        return

    logger.info(f"[{call_control_id}] Eva is handling: '{user_utterance}'")
    db = SessionLocal()
    state_channel = f"call_state:{call_control_id}"
    
    if call_control_id not in call_histories:
        call_histories[call_control_id] = []
        call_states[call_control_id] = "LISTENING" # Начальное состояние
    
    call_histories[call_control_id].append({"role": "user", "content": user_utterance})

    try:
        # 2. Устанавливаем состояние "SPEAKING" ПЕРЕД тем, как начать отвечать.
        call_states[call_control_id] = "SPEAKING"

        # --- Этапы NER и Retrieval (без изменений) ---
        entities = await extract_entities(user_utterance)
        await _publish_to_redis(redis_client, state_channel, {"type": "state_update", "entities": entities})

        db_results = []
        search_query = entities.get("policy_id") or entities.get("keywords")
        if entities.get("intent") == "claim_status_check" and search_query:
            claims = crud.search_claims(db=db, query=str(search_query))
            db_results = [{"policy_id": c.policy_id, "status": c.status.value} for c in claims]
        
        # --- Этап генерации (без изменений в логике, но теперь он "защищен" состоянием) ---
        final_prompt_messages = build_eva_prompt(call_histories[call_control_id], db_results, entities)
        
        full_response_text = await stream_llm_and_tts_eva(
            messages=final_prompt_messages,
            websocket=websocket,
            call_control_id=call_control_id,
        )

        if full_response_text:
            call_histories[call_control_id].append({"role": "assistant", "content": full_response_text})
            await _publish_to_redis(redis_client, state_channel, {"type": "transcript", "source": "bot", "text": full_response_text})

    except Exception as e:
        logger.error(f"[{call_control_id}] Error in Eva's logic: {e}", exc_info=True)
        # В случае ошибки тоже нужно озвучить сообщение
        error_message = "I'm sorry, I've encountered a technical issue. Please try again."
        await stream_tts_to_telnyx(error_message, websocket, call_control_id)
    finally:
        # 3. Возвращаем состояние "LISTENING" ПОСЛЕ того, как Ева закончила говорить.
        call_states[call_control_id] = "LISTENING"
        logger.info(f"[{call_control_id}] Eva is now LISTENING.")
        db.close()

async def _publish_to_redis(redis_client, channel: str, message_data: dict):
    try:
        if redis_client: await redis_client.publish(channel, json.dumps(message_data))
    except Exception as e:
        logger.error(f"Agent failed to publish to Redis channel {channel}: {e}")

def cleanup_call_resources(call_control_id: str):
    if call_control_id in call_histories:
        del call_histories[call_control_id]
    if call_control_id in call_states:
        del call_states[call_control_id]
    logger.info(f"Cleaned up resources for call {call_control_id}")