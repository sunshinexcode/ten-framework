import asyncio
from collections.abc import Callable
from time import time
from typing import AsyncIterator

import dashscope
from dashscope.audio.tts_v2 import (
    SpeechSynthesizer,
    AudioFormat,
    ResultCallback,
)

from .config import CosyTTSConfig
from ten_runtime import AsyncTenEnv

# Custom event types to communicate status back to the extension
EVENT_TTS_RESPONSE = 1
EVENT_TTS_END = 2
EVENT_TTS_ERROR = 3
EVENT_TTS_FLUSH = 4

# Audio format mapping constants
AUDIO_FORMAT_MAPPING = {
    8000: AudioFormat.PCM_8000HZ_MONO_16BIT,
    16000: AudioFormat.PCM_16000HZ_MONO_16BIT,
    22050: AudioFormat.PCM_22050HZ_MONO_16BIT,
    24000: AudioFormat.PCM_24000HZ_MONO_16BIT,
    44100: AudioFormat.PCM_44100HZ_MONO_16BIT,
    48000: AudioFormat.PCM_48000HZ_MONO_16BIT,
}
DEFAULT_AUDIO_FORMAT = AudioFormat.PCM_16000HZ_MONO_16BIT


class CosyTTSConnectionException(Exception):
    """Exception raised when Cosy TTS connection fails"""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Cosy TTS connection failed (code: {status_code}): {body}")


class AsyncIteratorCallback(ResultCallback):
    """Callback for handling TTS synthesis results with simplified architecture."""

    def __init__(
        self,
        ten_env: AsyncTenEnv,
        queue: asyncio.Queue[tuple[bytes | str | None, int | None]],
    ):
        self.ten_env = ten_env
        self._queue = queue
        self._error_message = None
        self._is_complete = False
        self._loop = asyncio.get_event_loop()

    def on_open(self):
        self.ten_env.log_info("TTS connection opened")

    def on_complete(self):
        self.ten_env.log_info("TTS synthesis completed")
        self._is_complete = True
        asyncio.run_coroutine_threadsafe(
            self._queue.put(("", EVENT_TTS_END)), self._loop
        )

    def on_error(self, message: str):
        self.ten_env.log_error(f"TTS synthesis error: {message}")
        self._error_message = message
        asyncio.run_coroutine_threadsafe(
            self._queue.put((message.encode(), EVENT_TTS_ERROR)), self._loop
        )

    def on_close(self):
        self.ten_env.log_info("TTS connection closed")

    def on_event(self, message: str):
        self.ten_env.log_debug(f"TTS event: {message}")

    def on_data(self, data: bytes):
        """Called when receiving audio data from TTS service."""
        if data and len(data) > 0:
            self.ten_env.log_debug(f"Received audio data: {len(data)} bytes")
            asyncio.run_coroutine_threadsafe(
                self._queue.put((data, EVENT_TTS_RESPONSE)), self._loop
            )
        else:
            self.ten_env.log_debug("Received empty audio data, skipping")

    async def get_audio_stream(
        self,
    ) -> AsyncIterator[tuple[bytes | str | None, int | None]]:
        """Get audio stream from the callback queue."""
        # while not self._is_complete and self._error_message is None:
        while True:
            try:
                audio_data, event_type = await asyncio.wait_for(
                    self._queue.get(), timeout=5
                )

                self.ten_env.log_debug(
                    f"CosyTTS: get_audio_stream, audio_data: {len(audio_data)} bytes, event_type: {event_type}"
                )
                yield audio_data, event_type

                if event_type == EVENT_TTS_END or event_type == EVENT_TTS_ERROR:
                    break

            except asyncio.TimeoutError:
                self.ten_env.log_warn(f"Timeout waiting for TTS audio data")
                break

        # Handle final states
        if self._error_message:
            yield self._error_message.encode(), EVENT_TTS_ERROR
        elif self._is_complete:
            yield "", EVENT_TTS_END


class CosyTTSClient:
    def __init__(
        self,
        config: CosyTTSConfig,
        ten_env: AsyncTenEnv,
        send_fatal_tts_error: Callable[[str], asyncio.Future[None]] | None = None,
        send_non_fatal_tts_error: Callable[[str], asyncio.Future[None]] | None = None,
    ):
        self.config = config
        self.ten_env: AsyncTenEnv = ten_env
        self.callback: AsyncIteratorCallback | None = None
        self.send_fatal_tts_error = send_fatal_tts_error
        self.send_non_fatal_tts_error = send_non_fatal_tts_error
        self.receive_queue: asyncio.Queue[tuple[bytes | str | None, int | None]] = (
            asyncio.Queue()
        )
        self.synthesizer: SpeechSynthesizer | None = None
        self._is_cancelled = False

        # Set dashscope API key
        dashscope.api_key = config.api_key

    async def start(self) -> None:
        """Preheating: establish TTS connection during initialization"""
        try:
            await self._connect()

        except Exception as e:
            self.ten_env.log_error(f"Cosy TTS connect failed: {e}")

    async def _connect(self) -> None:
        """Connect to the TTS service"""
        self.ten_env.log_debug(f"CosyTTS: _connect, synthesizer: {self.synthesizer}")
        try:
            start_time = time()
            self.receive_queue = asyncio.Queue()
            self.callback = AsyncIteratorCallback(self.ten_env, self.receive_queue)
            self.synthesizer = SpeechSynthesizer(
                callback=self.callback,
                format=self._get_audio_format(),
                model=self.config.model,
                voice=self.config.voice,
            )
            # Preheat the connection
            # self.synthesizer.streaming_call("")
            self.ten_env.log_info(
                f"Cosy TTS connected successfully, took: {time() - start_time}"
            )

        except Exception as e:
            self.ten_env.log_error(f"Cosy TTS preheat failed: {e}")

            error_message = str(e)
            # Cannot get the error message "websocket closed due to Handshake status 401 Unauthorized"
            # So we use a fixed string to check
            if "websocket connection could not established TODO" in error_message:
                if self.send_fatal_tts_error:
                    await self.send_fatal_tts_error(error_message)
                else:
                    raise CosyTTSConnectionException(
                        status_code=401, body=error_message
                    ) from e
            else:
                self.ten_env.log_error(f"Cosy TTS preheat failed,unexpected error: {e}")
                if self.send_non_fatal_tts_error:
                    await self.send_non_fatal_tts_error(error_message)
                raise

    async def stop(self):
        # Stop the TTS connection if it exists
        self.ten_env.log_info(f"CosyTTS: stop, synthesizer: {self.synthesizer}")
        pass
        if self.synthesizer:
            try:
                self.synthesizer.streaming_cancel()
            except Exception as e:
                self.ten_env.log_error(f"Error stopping TTS: {e}")
            finally:
                self.synthesizer = None
                self.callback = None

    async def cancel(self):
        """
        Cancel the current TTS task by stopping the synthesizer.
        This will trigger an exception in the processing loop.
        """
        self.ten_env.log_info("Cancelling current TTS task by stopping synthesizer.")
        self._is_cancelled = True
        if self.synthesizer:
            try:
                self.synthesizer.streaming_cancel()
            except Exception as e:
                self.ten_env.log_error(f"Error cancelling TTS: {e}")

    async def get(
        self, text: str, text_input_end: bool
    ) -> AsyncIterator[tuple[bytes | str | None, int | None]]:
        """Generate TTS audio for the given text, returns (audio_data, event_status)"""
        self.ten_env.log_debug(
            f"KEYPOINT generate_TTS for '{text}', text_input_end: {text_input_end}"
        )

        self._is_cancelled = False
        try:
            await self._ensure_connection()
            # Send TTS request and yield audio chunks with event status
            async for audio_chunk, event_status in self._process_single_tts(
                text, text_input_end
            ):
                self.ten_env.log_info(
                    f"CosyTTS: sending EVENT_TTS_RESPONSE, length: {len(audio_chunk)}, event_status: {event_status}"
                )
                yield audio_chunk, event_status

        except Exception as e:
            self.ten_env.log_error(f"Error in TTS get(): {e}")
            raise

    async def _ensure_connection(self) -> None:
        """Ensure TTS connection is established"""
        self.ten_env.log_info(
            f"CosyTTS: _ensure_connection, synthesizer: {self.synthesizer}"
        )
        if not self.synthesizer:
            await self._connect()

    async def _process_single_tts(
        self, text: str, text_input_end: bool
    ) -> AsyncIterator[tuple[bytes | str | None, int | None]]:
        """Process a single TTS request in serial manner"""
        self.ten_env.log_info(
            f"process_single_tts, text:{text}, text_input_end:{text_input_end}"
        )

        try:
            # Start synthesizer if not initialized
            # if self.synthesizer is None:
            #     await self.start()

            await self._ensure_connection()

            # Start streaming TTS synthesis
            self.synthesizer.streaming_call(text)
            if text_input_end:
                self.ten_env.log_debug("CosyTTS: streaming_complete")
                self.synthesizer.streaming_complete()
                self.synthesizer = None

            # Get audio stream from callback
            async for audio_data, event_type in self.callback.get_audio_stream():
                self.ten_env.log_debug(
                    f"CosyTTS: get_audio_stream, event_type: {event_type}"
                )

                if self._is_cancelled:
                    self.ten_env.log_info(
                        "Cancellation flag detected, sending flush event and stopping TTS stream."
                    )
                    yield "", EVENT_TTS_FLUSH
                    break

                if event_type == EVENT_TTS_RESPONSE and audio_data:
                    self.ten_env.log_info(
                        f"CosyTTS: sending EVENT_TTS_RESPONSE, length: {len(audio_data)}"
                    )
                    yield audio_data, EVENT_TTS_RESPONSE
                elif event_type == EVENT_TTS_END:
                    self.ten_env.log_info("CosyTTS: sending EVENT_TTS_END")
                    yield "", EVENT_TTS_END
                    break
                elif event_type == EVENT_TTS_ERROR:
                    if isinstance(audio_data, bytes):
                        error_msg = audio_data.decode()
                    elif isinstance(audio_data, str):
                        error_msg = audio_data
                    else:
                        error_msg = "Unknown error"
                    self.ten_env.log_error(f"CosyTTS failed: {error_msg}")
                    yield audio_data, EVENT_TTS_ERROR
                    break

        except Exception as e:
            error_message = str(e)
            self.ten_env.log_error(f"CosyTTS failed:{e}")
            yield error_message.encode("utf-8"), EVENT_TTS_ERROR

    def _get_audio_format(self) -> AudioFormat:
        """
        Automatically generate AudioFormat based on configuration.

        Returns:
            AudioFormat: The appropriate audio format for the configuration
        """
        if self.config.sample_rate in AUDIO_FORMAT_MAPPING:
            return AUDIO_FORMAT_MAPPING[self.config.sample_rate]

        # Fallback to default format if configuration not supported
        self.ten_env.log_warn(
            f"Unsupported audio format: {self.config.sample_rate}Hz, using default format: PCM_16000HZ_MONO_16BIT"
        )
        return DEFAULT_AUDIO_FORMAT
