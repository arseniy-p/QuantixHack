import os
import json
import base64
import asyncio
from starlette.websockets import WebSocketDisconnect
from .logger_config import logger

from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from deepgram.extensions.types.sockets import ListenV1SocketClientResponse


class CallProcessor:
    def __init__(self, call_control_id: str, websocket, redis_client):
        self.call_control_id = call_control_id
        self.websocket = websocket
        self.redis_client = redis_client
        self.state_channel = f"call_state:{self.call_control_id}"
        
        self.deepgram_client = AsyncDeepgramClient()
        
        self.full_transcript = []
        logger.info(f"CallProcessor created for call {self.call_control_id}")

    async def _publish_to_redis(self, message_data: dict):
        """Publishes a message to the call's Redis channel."""
        try:
            await self.redis_client.publish(self.state_channel, json.dumps(message_data))
        except Exception as e:
            logger.error(f"Failed to publish to Redis channel {self.state_channel}: {e}")

    async def process_user_utterance(self, utterance: str):
        user_message = {"type": "transcript", "source": "user", "text": utterance}
        asyncio.create_task(self._publish_to_redis(user_message))
        
        await asyncio.sleep(1.0) # Имитация работы LLM
        bot_response_text = f"I received your message: '{utterance}'. I am now processing it."
        bot_message = {"type": "transcript", "source": "bot", "text": bot_response_text}
        asyncio.create_task(self._publish_to_redis(bot_message))
        
        state_update = {"type": "state_update", "entities": {"topic": "car accident"}}
        asyncio.create_task(self._publish_to_redis(state_update))

    def _on_open(self, *args, **kwargs):
        """Handle connection open event"""
        logger.info(">>> Deepgram connection opened.")

    def _on_message(self, message: ListenV1SocketClientResponse, **kwargs):
        """
        Handle incoming transcription results from Deepgram.
        Accumulates partial results and processes complete utterances.
        Shows interim results in real-time for immediate feedback.
        """
        try:
            # Check if message has channel and alternatives
            if not hasattr(message, 'channel') or not hasattr(message.channel, 'alternatives'):
                return
            
            sentence = message.channel.alternatives[0].transcript
            if len(sentence) == 0:
                return
            
            # --- ЛОГИКА ОБНОВЛЕНА ---
            if message.is_final:
                self.full_transcript.append(sentence)
                
                if message.speech_final:
                    full_utterance = " ".join(self.full_transcript).strip()
                    logger.info(f"🎯 COMPLETE UTTERANCE: '{full_utterance}'")
                    
                    # Запускаем полную обработку только для завершенной фразы
                    asyncio.create_task(self.process_user_utterance(full_utterance))
                    
                    self.full_transcript = []
            else:
                # ЭТО ПРОМЕЖУТОЧНЫЙ РЕЗУЛЬТАТ - ОТПРАВЛЯЕМ ЕГО ДЛЯ ДИНАМИКИ
                logger.debug(f"💬 INTERIM: '{sentence}'")
                interim_message = {
                    "type": "interim_transcript", # <-- Новый тип сообщения!
                    "source": "user",
                    "text": " ".join(self.full_transcript + [sentence])
                }
                # Отправляем "в фоне", не дожидаясь
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
        """
        try:
            logger.info(f"Starting CallProcessor for {self.call_control_id}...")
            
            # Connect to Deepgram v1 with async context manager
            async with self.deepgram_client.listen.v1.connect(
                model="nova-3", # Optimized for phone calls
                language="en-US", 
                encoding="mulaw",          # Audio format from Telnyx
                sample_rate=8000,          # 8kHz sample rate from Telnyx
                channels=1,                # Mono audio
                interim_results=True,      # CRITICAL: Enable interim results for real-time feedback
                utterance_end_ms="1000",   # Detect end of utterance after 1 second of silence
                smart_format=True,         # Add punctuation and formatting
                vad_events=True,
                endpointing=300
            ) as connection:
                
                logger.info("Deepgram connection context entered")
                
                # Register event handlers
                connection.on(EventType.OPEN, self._on_open)
                connection.on(EventType.MESSAGE, self._on_message)
                connection.on(EventType.ERROR, self._on_error)
                connection.on(EventType.CLOSE, self._on_close)

                logger.info("Event handlers registered. Streaming audio...")

                # Create a task for Deepgram to start listening
                listen_task = asyncio.create_task(connection.start_listening())
                logger.info("Deepgram listening task started")

                # Main loop: receive audio from Telnyx and forward to Deepgram
                try:
                    while True:
                        message_str = await self.websocket.receive_text()
                        message = json.loads(message_str)

                        if message["event"] == "media":
                            # Decode base64 audio chunk and send to Deepgram
                            audio_chunk = base64.b64decode(message["media"]["payload"])
                            await connection.send_media(audio_chunk)
                            
                        elif message["event"] == "stop":
                            logger.info("Received stop event from Telnyx")
                            break
                            
                except WebSocketDisconnect:
                    logger.warning(f"Telnyx WebSocket disconnected for {self.call_control_id}.")
                finally:
                    # Cancel the listening task
                    logger.info("Cancelling Deepgram listening task...")
                    listen_task.cancel()
                    try:
                        await listen_task
                    except asyncio.CancelledError:
                        logger.info("Deepgram listening task cancelled successfully")

        except Exception as e:
            logger.error(
                f"An error occurred in CallProcessor run loop: {e}", exc_info=True
            )
        finally:
            logger.info(f"CallProcessor for {self.call_control_id} finished.")