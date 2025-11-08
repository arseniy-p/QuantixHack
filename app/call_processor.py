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
    def __init__(self, call_control_id: str, websocket):
        self.call_control_id = call_control_id
        self.websocket = websocket

        # Initialize Deepgram async client (API key is read from DEEPGRAM_API_KEY env var automatically)
        self.deepgram_client = AsyncDeepgramClient()

        self.full_transcript = []
        logger.info(f"CallProcessor created for call {self.call_control_id}")

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
            if not hasattr(message, "channel") or not hasattr(
                message.channel, "alternatives"
            ):
                return

            sentence = message.channel.alternatives[0].transcript

            if len(sentence) == 0:
                return

            # Check if this is a final result
            if message.is_final:
                self.full_transcript.append(sentence)
                logger.info(f"✅ USER SAID (FINAL): '{sentence}'")

                # OPTIMIZATION: Start preparing LLM context as soon as we have partial results
                # This allows us to reduce latency by starting to think before speech_final
                if len(self.full_transcript) >= 2:  # Have at least 2 segments
                    partial_utterance = " ".join(self.full_transcript).strip()
                    logger.debug(
                        f"🔄 Building context with partial: '{partial_utterance}'"
                    )
                    # TODO: You can start preparing LLM context here for faster response

                # Check if speech is complete (end of utterance)
                if message.speech_final:
                    full_utterance = " ".join(self.full_transcript).strip()
                    logger.info(f"🎯 COMPLETE UTTERANCE: '{full_utterance}'")

                    # TODO: Send to LLM for processing
                    logger.info(f"🤖 Ready to send to LLM: '{full_utterance}'")

                    # Clear transcript buffer for next utterance
                    self.full_transcript = []
            else:
                # INTERIM RESULTS - Real-time feedback while user is speaking
                # This gives immediate visual feedback that speech is being recognized
                logger.info(f"💬 INTERIM: '{sentence}'")

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
            # Connect to Deepgram v1 with async context manager
            async with (
                self.deepgram_client.listen.v1.connect(
                    model="nova-2-phonecall",  # Optimized for phone calls
                    encoding="mulaw",  # Audio format from Telnyx
                    sample_rate=8000,  # 8kHz sample rate from Telnyx
                    channels=1,  # Mono audio
                    interim_results=True,  # CRITICAL: Enable interim results for real-time feedback
                    utterance_end_ms="1000",  # Detect end of utterance after 1 second of silence
                    smart_format=True,  # Add punctuation and formatting
                ) as connection
            ):
                # Register event handlers
                connection.on(EventType.OPEN, self._on_open)
                connection.on(EventType.MESSAGE, self._on_message)
                connection.on(EventType.ERROR, self._on_error)
                connection.on(EventType.CLOSE, self._on_close)

                logger.info("Connection to Deepgram established. Streaming audio...")

                # Create a task for Deepgram to start listening
                listen_task = asyncio.create_task(connection.start_listening())

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
                    logger.warning(
                        f"Telnyx WebSocket disconnected for {self.call_control_id}."
                    )
                finally:
                    # Cancel the listening task
                    listen_task.cancel()
                    try:
                        await listen_task
                    except asyncio.CancelledError:
                        pass

        except Exception as e:
            logger.error(
                f"An error occurred in CallProcessor run loop: {e}", exc_info=True
            )
        finally:
            logger.info(f"CallProcessor for {self.call_control_id} finished.")
