# filename: app/agent_service.py

import json
import asyncio
from openai import AsyncOpenAI

from . import crud
from .database import SessionLocal
from .logger_config import logger
from .tts_service import stream_tts_to_telnyx

# --- LLM Configuration ---
client = AsyncOpenAI() # Reads OPENAI_API_KEY from environment
LLM_MODEL = "gpt-4-turbo" # Use a model that supports function calling well

# --- Define the "tool" or "function" the LLM can use ---
tools = [
    {
        "type": "function",
        "function": {
            "name": "search_claims_by_keyword",
            "description": "Searches the insurance claims database...",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "The user's search query..."}},
                "required": ["query"],
            },
        },
    }
]

SYSTEM_PROMPT = """You are a friendly and professional AI voice assistant..."""

async def _publish_to_redis(redis_client, channel: str, message_data: dict):
    try:
        if redis_client:
            await redis_client.publish(channel, json.dumps(message_data))
    except Exception as e:
        logger.error(f"Agent failed to publish to Redis channel {channel}: {e}")

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
        # Step 1 & 2: LLM with Function Calling for NER/Intent
        initial_response = await client.chat.completions.create(
            model=LLM_MODEL, messages=[{"role": "user", "content": user_utterance}],
            tools=tools, tool_choice="auto",
        )
        response_message = initial_response.choices[0].message
        tool_calls = response_message.tool_calls
        
        api_results = []
        if tool_calls:
            tool_call_args = {}
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                if function_name == "search_claims_by_keyword":
                    args = json.loads(tool_call.function.arguments)
                    tool_call_args = args
                    claims = crud.search_claims(db=db, query=args.get("query"))
                    for claim in claims:
                        api_results.append({
                            "policy_id": claim.policy_id, "status": claim.status.value,
                            "incident_type": claim.incident_type
                        })
            
            # Publish extracted state to Redis
            state_update_msg = {"type": "state_update", "entities": {"tool_call": tool_call_args, "results_found": len(api_results)}}
            asyncio.create_task(_publish_to_redis(redis_client, state_channel, state_update_msg))

        # Step 4: Generate Final Text Response
        final_prompt_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_utterance},
            {"role": "assistant", "content": f"I have searched the database. Here are the results: {json.dumps(api_results)}"}
        ]
        final_response = await client.chat.completions.create(model=LLM_MODEL, messages=final_prompt_messages)
        bot_response_text = final_response.choices[0].message.content
        logger.info(f"[{call_control_id}] Generated bot response: '{bot_response_text}'")

        if bot_response_text:
            # Publish the bot's response to Redis
            bot_message = {"type": "transcript", "source": "bot", "text": bot_response_text}
            asyncio.create_task(_publish_to_redis(redis_client, state_channel, bot_message))

            # Step 5: Stream the response as audio
            await stream_tts_to_telnyx(bot_response_text, websocket, call_control_id)

    except Exception as e:
        logger.error(f"[{call_control_id}] Error in agent_service: {e}", exc_info=True)
        error_message = "I'm sorry, I encountered a technical issue."
        err_msg_redis = {"type": "transcript", "source": "bot", "text": error_message}
        asyncio.create_task(_publish_to_redis(redis_client, state_channel, err_msg_redis))
        await stream_tts_to_telnyx(error_message, websocket, call_control_id)
    finally:
        db.close()