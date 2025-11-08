# filename: app/agent_service.py

import json
import asyncio
from openai import AsyncOpenAI

from . import crud
from .database import SessionLocal
from .logger_config import logger
from .tts_service import stream_tts_to_telnyx

client = AsyncOpenAI() 
LLM_MODEL = "gpt-3.5-turbo" #
tools = [
    {
        "type": "function", "function": { "name": "search_claims_by_keyword",
            "description": "Searches the database for insurance claims. Use this for ANY user request about the status of their auto, home, or medical claim, policy, or incident.",
            "parameters": { "type": "object", "properties": { "query": { "type": "string",
                        "description": "Keywords from the user's request, like 'car accident', 'water damage', or a policy number like 'POL-123'.",
                    }}, "required": ["query"],
            },
        },
    }
]
SYSTEM_PROMPT = """
You are a friendly, conversational AI voice assistant for an insurance company. Your goal is to help users check the status of their insurance claims.

**Your Conversation Flow:**
1.  **Greeting:** Start with a simple, friendly greeting. If the user just says "Hello", greet them back and ask how you can help (e.g., "Hello! How can I help you today?"). Do NOT immediately jump to your function.
2.  **Information Gathering:** The user will ask about their claim. Their first query might be vague (e.g., "I want to check my status"). Your job is to recognize this. If you do not have a specific Policy ID, incident type, or date, you MUST ask a clarifying question. Examples: "I can certainly help with that. Could you please provide your policy number?" or "To find your claim, could you tell me what the claim was about, for example, a car accident or water damage?"
3.  **Tool Usage:** Only use the 'search_claims_by_keyword' tool AFTER you have gathered a specific piece of information (like a policy number or a concrete incident description like "my car accident on May 5th"). Do not use the tool with vague queries like "my claim".
4.  **Responding with Data:** Once the tool returns data, present it clearly and concisely.
"""

async def _publish_to_redis(redis_client, channel: str, message_data: dict):
    try:
        if redis_client:
            await redis_client.publish(channel, json.dumps(message_data))
    except Exception as e:
        logger.error(f"Agent failed to publish to Redis channel {channel}: {e}")

async def stream_llm_and_tts(messages: list, websocket, call_control_id: str, redis_client, state_channel: str):
    """
    Управляет двусторонним стримингом: получает текст от LLM и отправляет его в TTS по предложениям.
    """
    sentence_buffer = ""
    full_response_text = ""
    sentence_enders = [".", "?", "!"]

    logger.info(f"[{call_control_id}] Starting LLM stream...")
    try:
        response_stream = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            stream=True
        )

        async for chunk in response_stream:
            text_chunk = chunk.choices[0].delta.content
            if not text_chunk:
                continue

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

        logger.info(f"[{call_control_id}] Full generated response: '{full_response_text}'")
        bot_message = {"type": "transcript", "source": "bot", "text": full_response_text}
        await _publish_to_redis(redis_client, state_channel, bot_message)

    except Exception as e:
        logger.error(f"[{call_control_id}] Error during LLM/TTS stream: {e}", exc_info=True)


async def handle_user_input(
    user_utterance: str,
    call_control_id: str,
    websocket,
    redis_client
):
    logger.info(f"[{call_control_id}] Handling user utterance: '{user_utterance}'")
    db = SessionLocal()
    state_channel = f"call_state:{call_control_id}"
    try:
        initial_response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": user_utterance}],
            tools=tools,
            tool_choice="auto",
        )
        response_message = initial_response.choices[0].message
        tool_calls = response_message.tool_calls
        
        api_results = []
        if tool_calls:
            tool_call_args = {}
            for tool_call in tool_calls:
                if tool_call.function.name == "search_claims_by_keyword":
                    args = json.loads(tool_call.function.arguments)
                    tool_call_args = args
                    claims = crud.search_claims(db=db, query=args.get("query"))
                    api_results = [
                        {"policy_id": c.policy_id, "status": c.status.value} for c in claims
                    ]
            
            state_update_msg = {"type": "state_update", "entities": {"tool_call": tool_call_args, "results_found": len(api_results)}}
            asyncio.create_task(_publish_to_redis(redis_client, state_channel, state_update_msg))

        final_prompt_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_utterance},
            {"role": "assistant", "content": f"I have searched the database. Here are the results: {json.dumps(api_results)}"}
        ]
        
        await stream_llm_and_tts(
            messages=final_prompt_messages,
            websocket=websocket,
            call_control_id=call_control_id,
            redis_client=redis_client,
            state_channel=state_channel
        )

    except Exception as e:
        logger.error(f"[{call_control_id}] Error in handle_user_input: {e}", exc_info=True)
        error_message = "I'm sorry, I encountered a technical issue."
        err_msg_redis = {"type": "transcript", "source": "bot", "text": error_message}
        asyncio.create_task(_publish_to_redis(redis_client, state_channel, err_msg_redis))
        await stream_tts_to_telnyx(error_message, websocket, call_control_id)
    finally:
        db.close()