# filename: app/call_processor.py

import json
import base64
import asyncio
from starlette.websockets import WebSocketDisconnect
from .logger_config import logger

from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType

from . import agent_service

# Создаем один клиент Deepgram для всего приложения
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
        try:
            await self.redis_client.publish(self.state_channel, json.dumps(message_data))
        except Exception as e:
            logger.error(f"Failed to publish to Redis channel {self.state_channel}: {e}")

    async def process_user_utterance(self, utterance: str):
        if not utterance: return
        
        user_message = {"type": "transcript", "source": "user", "text": utterance}
        asyncio.create_task(self._publish_to_redis(user_message))
        
        asyncio.create_task(
            agent_service.handle_user_input(
                user_utterance=utterance,
                call_control_id=self.call_control_id,
                websocket=self.websocket,
                redis_client=self.redis_client
            )
        )

    def _on_message(self, message, **kwargs):
        try:
            sentence = message.channel.alternatives[0].transcript
            if not sentence: return
            
            if message.is_final:
                self.full_transcript.append(sentence)
                if message.speech_final:
                    full_utterance = " ".join(self.full_transcript).strip()
                    self.full_transcript = []
                    logger.info(f"🎯 COMPLETE UTTERANCE: '{full_utterance}'")
                    asyncio.create_task(self.process_user_utterance(full_utterance))
            else:
                interim_text = " ".join(self.full_transcript + [sentence])
                logger.debug(f"💬 INTERIM: '{interim_text}'")
                interim_message = {"type": "interim_transcript", "source": "user", "text": interim_text}
                asyncio.create_task(self._publish_to_redis(interim_message))
        except Exception as e:
            logger.error(f"Error processing Deepgram message: {e}", exc_info=True)

    def _on_open(self, *args, **kwargs): logger.info(">>> Deepgram connection opened.")
    def _on_error(self, error, **kwargs): logger.error(f"!!! Deepgram error: {error}")
    def _on_close(self, *args, **kwargs): logger.info(">>> Deepgram connection closed.")

    async def run(self):
        """
        Главный цикл с "жесткими" настройками для Deepgram Nova-2 для быстрого отклика.
        """
        try:
            async with self.deepgram_client.listen.v1.connect(
                model="nova-2-phonecall",
                language="en-US",
                encoding="mulaw",
                sample_rate=8000,
                smart_format=True,
                interim_results=True,
                # Ключевые параметры для быстрого определения конца фразы
                utterance_end_ms="700",
                endpointing="300",
            ) as connection:
                connection.on(EventType.OPEN, self._on_open)
                connection.on(EventType.MESSAGE, self._on_message)
                connection.on(EventType.ERROR, self._on_error)
                connection.on(EventType.CLOSE, self._on_close)
                try:
                    while True:
                        message_str = await self.websocket.receive_text()
                        message = json.loads(message_str)
                        if message["event"] == "media":
                            audio_chunk = base64.b64decode(message["media"]["payload"])
                            # Отправляем аудио напрямую, без конвертации
                            await connection.send_media(audio_chunk)
                        elif message["event"] == "stop":
                            break
                except WebSocketDisconnect:
                    logger.warning(f"Telnyx WebSocket disconnected.")
        except Exception as e:
            logger.error(f"An error occurred in CallProcessor run loop: {e}", exc_info=True)
        finally:
            logger.info(f"CallProcessor for {self.call_control_id} finished.")