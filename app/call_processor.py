# filename: app/call_processor.py

import os
import json
import base64
import asyncio
from starlette.websockets import WebSocketDisconnect
from .logger_config import logger

from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from deepgram.extensions.types.sockets import ListenV1SocketClientResponse

# ### ИЗМЕНЕНИЕ 1: Импортируем новый сервис-агент ###
from . import agent_service

deepgram_client = AsyncDeepgramClient()

class CallProcessor:
    def __init__(self, call_control_id: str, websocket, redis_client):
        self.call_control_id = call_control_id
        self.websocket = websocket
        self.redis_client = redis_client
        self.state_channel = f"call_state:{self.call_control_id}"
        self.deepgram_client = deepgram_client
        
        self.full_transcript = []
        logger.info(f"CallProcessor created for call {self.call_control_id}")

    async def _publish_to_redis(self, message_data: dict):
        """Publishes a message to the call's Redis channel."""
        try:
            await self.redis_client.publish(self.state_channel, json.dumps(message_data))
        except Exception as e:
            logger.error(f"Failed to publish to Redis channel {self.state_channel}: {e}")

    # ### ИЗМЕНЕНИЕ 2: Заменяем имитацию на вызов реальной логики ###
    async def process_user_utterance(self, utterance: str):
        """
        This method is now the bridge between transcription and the AI agent.
        """
        # 1. Publish the final user transcript to Redis for the dashboard.
        # This part remains from your original code.
        user_message = {"type": "transcript", "source": "user", "text": utterance}
        asyncio.create_task(self._publish_to_redis(user_message))
        
        # 2. Instead of simulating, we now call the actual agent service.
        # This service will handle NER, DB search, LLM response, and TTS.
        # We pass all necessary components to it.
        asyncio.create_task(
            agent_service.handle_user_input(
                user_utterance=utterance,
                call_control_id=self.call_control_id,
                websocket=self.websocket,
                redis_client=self.redis_client
            )
        )

    # --- ОСТАЛЬНАЯ ЧАСТЬ ФАЙЛА ОСТАЕТСЯ БЕЗ ИЗМЕНЕНИЙ ---
    # Ваша рабочая логика Deepgram и WebSocket сохранена в целости.

    def _on_open(self, *args, **kwargs):
        """Handle connection open event"""
        logger.info(">>> Deepgram connection opened.")

    def _on_message(self, message: ListenV1SocketClientResponse, **kwargs):
        """
        Handle incoming transcription results from Deepgram.
        (This is your working code - no changes needed here)
        """
        try:
            if not hasattr(message, 'channel') or not hasattr(message.channel, 'alternatives'):
                return
            
            sentence = message.channel.alternatives[0].transcript
            if len(sentence) == 0:
                return
            
            if message.is_final:
                self.full_transcript.append(sentence)
                
                if message.speech_final:
                    full_utterance = " ".join(self.full_transcript).strip()
                    logger.info(f"🎯 COMPLETE UTTERANCE: '{full_utterance}'")
                    
                    asyncio.create_task(self.process_user_utterance(full_utterance))
                    
                    self.full_transcript = []
            else:
                logger.debug(f"💬 INTERIM: '{sentence}'")
                interim_message = {
                    "type": "interim_transcript",
                    "source": "user",
                    "text": " ".join(self.full_transcript + [sentence])
                }
                asyncio.create_task(self._publish_to_redis(interim_message))
                
        except Exception as e:
            logger.error(f"Error processing Deepgram message: {e}", exc_info=True)

    def _on_error(self, error, **kwargs):
        """Handle error events"""
        logger.error(f"!!! Deepgram error: {error}")

    def _on_close(self, *args, **kwargs):
        """Handle connection close event"""
        logger.info(">>> Deepgram connection closed.")

    async def run(self):
        """
        Main processing loop: connects to Deepgram and forwards audio chunks.
        (This is your working code - no changes needed here)
        """
        try:
            logger.info(f"Starting CallProcessor for {self.call_control_id}...")
            
            async with self.deepgram_client.listen.v1.connect(
                model="nova-2-phonecall", language="en-US", encoding="mulaw",
                sample_rate=8000, channels=1, interim_results=True,
                utterance_end_ms="1500", smart_format=True, vad_events=True,
                endpointing=300, numerals=True, keywords=["POL:5"]
            ) as connection:
                
                connection.on(EventType.OPEN, self._on_open)
                connection.on(EventType.MESSAGE, self._on_message)
                connection.on(EventType.ERROR, self._on_error)
                connection.on(EventType.CLOSE, self._on_close)

                logger.info("Event handlers registered. Streaming audio...")

                listen_task = asyncio.create_task(connection.start_listening())
                logger.info("Deepgram listening task started")

                try:
                    while True:
                        message_str = await self.websocket.receive_text()
                        message = json.loads(message_str)

                        if message["event"] == "media":
                            audio_chunk = base64.b64decode(message["media"]["payload"])
                            await connection.send_media(audio_chunk)
                            
                        elif message["event"] == "stop":
                            logger.info("Received stop event from Telnyx")
                            break
                            
                except WebSocketDisconnect:
                    logger.warning(f"Telnyx WebSocket disconnected for {self.call_control_id}.")
                finally:
                    logger.info("Cancelling Deepgram listening task...")
                    listen_task.cancel()
                    try:
                        await listen_task
                    except asyncio.CancelledError:
                        logger.info("Deepgram listening task cancelled successfully")
        except Exception as e:
            logger.error(f"An error occurred in CallProcessor run loop: {e}", exc_info=True)
        finally:
            logger.info(f"CallProcessor for {self.call_control_id} finished.")