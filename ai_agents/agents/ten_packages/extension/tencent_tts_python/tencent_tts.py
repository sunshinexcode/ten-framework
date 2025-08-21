import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import datetime
import json
import urllib.parse
import uuid
import websockets

from .src.common import credential
from .src.flowing_speech_synthesizer import (
    FlowingSpeechSynthesizer,
    FlowingSpeechSynthesizer_ACTION_SYNTHESIS,
    FlowingSpeechSynthesizer_ACTION_COMPLETE,
)

from ten_runtime.async_ten_env import AsyncTenEnv
from .config import TencentTTSConfig


# Custom event types to communicate status back to the extension
EVENT_TTS_RESPONSE = 1
EVENT_TTS_END = 2
EVENT_TTS_ERROR = 3
EVENT_TTS_FLUSH = 4

# Error code reference: https://cloud.tencent.com/document/product/1073/108595
ERROR_CODE_AUTHORIZATION_FAILED = 10003


class TencentTTSTaskFailedException(Exception):
    """Exception raised when Tencent TTS task fails"""

    error_code: int
    error_msg: str

    def __init__(self, error_code: int, error_msg: str):
        self.error_code = error_code
        self.error_msg = error_msg
        super().__init__(f"TTS task failed: {error_msg} (code: {error_code})")


class TencentTTSClient:
    def __init__(
        self,
        config: TencentTTSConfig,
        ten_env: AsyncTenEnv,
        send_fatal_tts_error: Callable[[str], asyncio.Future] | None = None,
        send_non_fatal_tts_error: Callable[[str], asyncio.Future] | None = None,
    ):
        # Configuration and environment
        self.config = config
        self.ten_env = ten_env
        self.send_fatal_tts_error = send_fatal_tts_error
        self.send_non_fatal_tts_error = send_non_fatal_tts_error
        self.ws: websockets.ClientConnection | None = None
        self._is_cancelled = False
        self._synthesizer: FlowingSpeechSynthesizer | None = None

    async def start(self) -> None:
        """Preheating: establish websocket connection during initialization"""
        try:
            await self._connect()
        except Exception as e:
            self.ten_env.log_error(f"Tencent TTS preheat failed: {e}")

    async def _connect(self) -> None:
        """Connect to the websocket"""
        try:
            start_time = datetime.now()

            # Initialize synthesizer
            credential_var = credential.Credential(
                secret_key=self.config.secret_key, secret_id=self.config.secret_id
            )
            self._synthesizer = FlowingSpeechSynthesizer(
                self.config.app_id, credential_var, None
            )
            self._synthesizer.set_codec(self.config.codec)
            self._synthesizer.set_emotion_category(self.config.emotion_category)
            self._synthesizer.set_emotion_intensity(self.config.emotion_intensity)
            self._synthesizer.set_enable_subtitle(self.config.enable_words)
            self._synthesizer.set_sample_rate(self.config.sample_rate)
            self._synthesizer.set_speed(self.config.speed)
            self._synthesizer.set_voice_type(self.config.voice_type)
            self._synthesizer.set_volume(self.config.volume)

            # Establish WebSocket connection
            self.ws = await websockets.connect(self._gen_ws_url())

            self.ten_env.log_info(
                f"Tencent TTS websocket connected successfully, took: {self._duration_in_ms_since(start_time)}ms"
            )

        except Exception as e:
            self.ten_env.log_error(f"Tencent TTS connect failed: {e}")

            error_message = str(e)
            if "401" in error_message or "authorization" in error_message.lower():
                if self.send_fatal_tts_error:
                    await self.send_fatal_tts_error(error_message)
                else:
                    raise TencentTTSTaskFailedException(401, error_message) from e
            else:
                self.ten_env.log_error(
                    f"Tencent TTS preheat failed, unexpected error: {e}"
                )
                if self.send_non_fatal_tts_error:
                    await self.send_non_fatal_tts_error(error_message)
                raise

    async def stop(self) -> None:
        """Stop the websocket connection if it exists"""
        if self.ws:
            await self.ws.close()
            self.ws = None

    async def cancel(self) -> None:
        """Cancel the current TTS task by closing the websocket connection"""
        self.ten_env.log_debug("Cancelling current TTS task by closing websocket.")
        self._is_cancelled = True
        if self.ws:
            await self.ws.close()

    async def get(self, text: str) -> AsyncIterator[tuple[bytes | None, int | None]]:
        """Generate TTS audio for the given text, returns (audio_data, event_status)"""
        self.ten_env.log_debug(f"KEYPOINT generate_TTS for '{text}'")

        self._is_cancelled = False
        try:
            await self._ensure_connection()
            # Send TTS request and yield audio chunks with event status
            async for audio_chunk, event_status in self._process_single_tts(text):
                yield audio_chunk, event_status

        except Exception as e:
            self.ten_env.log_error(f"Error in TTS get(): {e}")
            raise

    async def _ensure_connection(self) -> None:
        """Ensure websocket connection is established"""
        if not self.ws:
            await self._connect()

    async def _process_single_tts(
        self, text: str
    ) -> AsyncIterator[tuple[bytes | None, int]]:
        """Process a single TTS request in serial manner"""
        if not self.ws:
            self.ten_env.log_error("Tencent TTS websocket not connected")
            return

        self.ten_env.log_info(f"process_single_tts, text: {text}")

        try:
            # Send synthesis request
            synthesis_data = json.dumps(
                self._synthesizer._FlowingSpeechSynthesizer__new_ws_request_message(
                    FlowingSpeechSynthesizer_ACTION_SYNTHESIS, text
                )
            )
            await self.ws.send(synthesis_data, text=True)

            # Send complete request
            complete_data = json.dumps(
                self._synthesizer._FlowingSpeechSynthesizer__new_ws_request_message(
                    FlowingSpeechSynthesizer_ACTION_COMPLETE, ""
                )
            )
            await self.ws.send(complete_data, text=True)

            # Process responses
            while True:
                if self._is_cancelled:
                    self.ten_env.log_info(
                        "Cancellation flag detected, sending flush event and stopping TTS stream."
                    )
                    yield None, EVENT_TTS_FLUSH
                    break

                try:
                    message = await asyncio.wait_for(self.ws.recv(), timeout=5)
                except asyncio.TimeoutError:
                    self.ten_env.log_error("Tencent TTS response timeout")
                    # Fix: Close WebSocket connection on timeout to prevent hanging
                    if self.ws:
                        try:
                            await self.ws.close()
                            self.ws = None
                            self.ten_env.log_info(
                                "WebSocket connection closed due to timeout"
                            )
                        except Exception as close_error:
                            self.ten_env.log_error(
                                f"Error closing WebSocket on timeout: {close_error}"
                            )
                    break
                except websockets.exceptions.ConnectionClosed:
                    self.ten_env.log_warn(
                        "WebSocket connection closed, attempting reconnection..."
                    )
                    try:
                        await self._connect()
                        # Retry the request after reconnection
                        synthesis_data = json.dumps(
                            self._synthesizer._FlowingSpeechSynthesizer__new_ws_request_message(
                                FlowingSpeechSynthesizer_ACTION_SYNTHESIS, text
                            )
                        )
                        await self.ws.send(synthesis_data, text=True)
                        complete_data = json.dumps(
                            self._synthesizer._FlowingSpeechSynthesizer__new_ws_request_message(
                                FlowingSpeechSynthesizer_ACTION_COMPLETE, ""
                            )
                        )
                        await self.ws.send(complete_data, text=True)
                        continue
                    except Exception as reconnect_error:
                        self.ten_env.log_error(
                            f"Reconnection failed: {reconnect_error}"
                        )
                        yield str(reconnect_error).encode("utf-8"), EVENT_TTS_ERROR
                        break

                if isinstance(message, str):
                    resp = json.loads(message)
                    if resp["code"] != 0:
                        if resp["code"] == ERROR_CODE_AUTHORIZATION_FAILED:
                            if self.send_fatal_tts_error:
                                await self.send_fatal_tts_error(resp["message"])
                            yield resp["message"].encode("utf-8"), EVENT_TTS_ERROR
                        else:
                            if self.send_non_fatal_tts_error:
                                await self.send_non_fatal_tts_error(resp["message"])
                            yield resp["message"].encode("utf-8"), EVENT_TTS_ERROR
                        break

                    if "final" in resp and resp["final"] == 1:
                        self.ten_env.log_info("Tencent TTS: sending EVENT_TTS_END")
                        yield None, EVENT_TTS_END
                        break

                elif isinstance(message, bytes):
                    if len(message) > 0:
                        self.ten_env.log_info(
                            f"Tencent TTS: sending EVENT_TTS_RESPONSE, length: {len(message)}"
                        )
                        yield message, EVENT_TTS_RESPONSE

        except Exception as e:
            error_message = str(e)
            self.ten_env.log_error(f"Tencent TTS failed: {e}")
            yield error_message.encode("utf-8"), EVENT_TTS_ERROR

    def _gen_ws_url(self) -> str:
        """Generate WebSocket URL for Tencent TTS service"""
        session_id = str(uuid.uuid1())
        params = self._synthesizer._FlowingSpeechSynthesizer__gen_params(session_id)
        signature = self._synthesizer._FlowingSpeechSynthesizer__gen_signature(params)
        req_url = self._synthesizer._FlowingSpeechSynthesizer__create_query_string(
            params
        )
        req_url += "&Signature=%s" % urllib.parse.quote(signature)
        return req_url

    def _duration_in_ms_since(self, start: datetime) -> int:
        """Calculate duration from a timestamp to now in milliseconds"""
        return int((datetime.now() - start).total_seconds() * 1000)
