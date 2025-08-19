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


MESSAGE_TYPE_PCM = 1
MESSAGE_TYPE_ERROR = 2

# WebSocket command constants
WS_CMD_STOP = "stop"
WS_CMD_CANCEL = "cancel"

# Error code reference: https://cloud.tencent.com/document/product/1073/108595
ERROR_CODE_INVALID_PARAMS = 10001
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
        vendor: str,
        send_fatal_tts_error: Callable[[str], asyncio.Future] | None = None,
        send_non_fatal_tts_error: Callable[[str], asyncio.Future] | None = None,
    ):
        # Configuration and environment
        self.config = config
        self.ten_env = ten_env
        self.vendor = vendor
        self.send_fatal_tts_error = send_fatal_tts_error
        self.send_non_fatal_tts_error = send_non_fatal_tts_error

        # Session management
        self.session_id: str = ""

        # Communication queues and components
        self._receive_queue: (
            asyncio.Queue[tuple[bool, int, bytes, dict[str, object]]] | None
        ) = None
        self._synthesizer: FlowingSpeechSynthesizer | None = None
        self._ws: websockets.ClientConnection | None = None
        self._ws_cmd_queue: asyncio.Queue[dict[str, object]] | None = None
        self._ws_need_wait_ready_event: asyncio.Event | None = None
        self._ws_receive_task: asyncio.Task[None] | None = None

        # Retry control flag
        self._reconnect_allowed: bool = True

    async def cancel(self) -> None:
        """
        Cancel current TTS operation.

        Sends a cancel command to the WebSocket receive task to stop
        the current TTS synthesis operation.
        """
        await self._ws_cmd_queue.put(WS_CMD_CANCEL)
        self.ten_env.log_info("_ws_receive_task had cancel done")

    async def start(self):
        """
        Initialize and start the TTS client.

        This method:
        1. Creates credentials using config secrets
        2. Initializes the speech synthesizer with configuration
        3. Sets up all TTS parameters (codec, emotion, sample rate, etc.)
        4. Creates async queues for communication
        5. Establishes WebSocket connection
        6. Starts the receive task for handling responses
        """
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

        self._receive_queue = asyncio.Queue()
        self._ws_cmd_queue = asyncio.Queue()

        self._ws_receive_task = asyncio.create_task(
            self._receive_tts_response_and_cmd()
        )
        await self._ws_reconnect()  # make sure tcp handshare in advance
        self.ten_env.log_info("tencent tts start done")

    async def stop(self) -> None:
        """
        Close the TTS client and cleanup resources.

        Sends a stop command to the WebSocket receive task and waits
        for it to complete before returning.
        """
        self.ten_env.log_info("tencent tts stop start")
        try:
            await self._ws_cmd_queue.put(WS_CMD_STOP)

            if self._ws_receive_task:
                try:
                    await self._ws_receive_task
                except Exception as e:
                    self.ten_env.log_error(
                        f"Error waiting for WebSocket receive task: {e}"
                    )
                    # Continue with cleanup even if task has errors
                finally:
                    self._ws_receive_task = None

            self.ten_env.log_info("_ws_receive_task had close done")
        except Exception as e:
            self.ten_env.log_error(f"Error during TTS client stop: {e}")

    async def synthesize_audio(
        self,
        text: str,
    ) -> AsyncIterator[tuple[bool, str, bytes | dict[str, object]]]:
        """Convert text to speech audio stream."""
        self.ten_env.log_info(f"tencent tts synthesize_audio start, text: {text}")
        start_time = datetime.now()

        try:
            if self._ws_need_wait_ready_event != None:
                await asyncio.wait_for(self._ws_need_wait_ready_event.wait(), timeout=5)

            data = json.dumps(
                # TODO(lint)
                # pylint: disable=protected-access
                self._synthesizer._FlowingSpeechSynthesizer__new_ws_request_message(
                    FlowingSpeechSynthesizer_ACTION_SYNTHESIS, text
                )
            )

            await self._ws.send(data, text=True)
            data = json.dumps(
                # TODO(lint)
                # pylint: disable=protected-access
                self._synthesizer._FlowingSpeechSynthesizer__new_ws_request_message(
                    FlowingSpeechSynthesizer_ACTION_COMPLETE, ""
                )
            )
            await self._ws.send(data, text=True)

            while True:
                tts_response = await asyncio.wait_for(
                    self._receive_queue.get(), timeout=5
                )

                yield tts_response

                # Final
                if tts_response[0] == True:
                    break

        except asyncio.TimeoutError:
            self.ten_env.log_error("tencent tts get response timeout")

        except Exception as e:
            self.ten_env.log_error(f"get tencent tts get error:{e}")

        finally:
            self.ten_env.log_info(
                f"websocket loop done, duration {self._duration_in_ms_since(start_time)}ms"
            )

    def _duration_in_ms(self, start: datetime, end: datetime) -> int:
        """
        Calculate duration between two timestamps in milliseconds.

        Args:
            start: Start timestamp
            end: End timestamp

        Returns:
            Duration in milliseconds
        """
        return int((end - start).total_seconds() * 1000)

    def _duration_in_ms_since(self, start: datetime) -> int:
        """
        Calculate duration from a timestamp to now in milliseconds.

        Args:
            start: Start timestamp

        Returns:
            Duration in milliseconds from start to now
        """
        return self._duration_in_ms(start, datetime.now())

    def _gen_ws_url(self) -> str:
        """
        Generate WebSocket URL for Tencent TTS service.

        This method creates a signed WebSocket URL by:
        1. Generating a unique session ID
        2. Creating request parameters with the session ID
        3. Generating a signature using the parameters
        4. Building the final URL with the signature

        Returns:
            str: Complete WebSocket URL with authentication signature
        """
        session_id = str(uuid.uuid1())
        # TODO(lint)
        # pylint: disable=protected-access
        params = self._synthesizer._FlowingSpeechSynthesizer__gen_params(session_id)
        # TODO(lint)
        # pylint: disable=protected-access
        signature = self._synthesizer._FlowingSpeechSynthesizer__gen_signature(params)
        # TODO(lint)
        # pylint: disable=protected-access
        req_url = self._synthesizer._FlowingSpeechSynthesizer__create_query_string(
            params
        )
        req_url += "&Signature=%s" % urllib.parse.quote(signature)

        return req_url

    async def _receive_tts_response_and_cmd(self):
        """
        Main loop for receiving TTS responses and handling commands.

        This method runs continuously to:
        1. Wait for WebSocket messages or commands
        2. Process TTS responses (audio data, final signals, etc.)
        3. Handle control commands (stop, cancel)
        4. Manage WebSocket reconnection on errors

        The method uses asyncio.wait to handle both command queue
        and WebSocket receive operations concurrently.
        """
        while True:
            # Check if WebSocket reconnection is allowed at the beginning of each loop iteration
            if not self._reconnect_allowed:
                self.ten_env.log_error(
                    "WebSocket reconnection disabled, stopping TTS response loop"
                )
                return

            try:
                if self._ws_need_wait_ready_event != None:
                    await asyncio.wait_for(
                        self._ws_need_wait_ready_event.wait(), timeout=5
                    )

                done, pending = await asyncio.wait(
                    [self._ws_cmd_queue.get(), self._ws.recv()],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()

                for completed_task in done:
                    result = completed_task.result()

                    if isinstance(result, str):
                        if result == WS_CMD_STOP:
                            await self._ws_close()
                            return
                        elif result == WS_CMD_CANCEL:
                            await self._ws_reconnect()
                        else:
                            resp = json.loads(result)
                            if resp["code"] != 0:
                                self.ten_env.log_error(
                                    f"_receive_tts_response_and_cmd tencent tts get error:{resp}"
                                )
                                raise TencentTTSTaskFailedException(
                                    resp["code"], resp["message"]
                                )

                            if "final" in resp and resp["final"] == 1:
                                await self._receive_queue.put(
                                    (True, MESSAGE_TYPE_PCM, b"")
                                )
                                await self._ws_reconnect()
                            elif "heartbeat" in resp and resp["heartbeat"] == 1:
                                pass
                            elif "result" in resp:
                                pass
                            else:
                                self.ten_env.log_warn(
                                    f"_receive_tts_reponse tencent tts recieve unsupport message:{resp}"
                                )

                    elif isinstance(result, bytes):
                        if len(result) > 0:
                            await self._receive_queue.put(
                                (False, MESSAGE_TYPE_PCM, result)
                            )

                    else:
                        raise TypeError("tts resp message type is not str and bytes")

            except TencentTTSTaskFailedException as e:
                self.ten_env.log_error(
                    f"_receive_tts_response_and_cmd tencent tts get error:{e}"
                )
                raise e

            except Exception as e:
                self._reconnect_allowed = False
                self.ten_env.log_error(
                    f"_recieve_tts_reponse tencent tts get error:{e}"
                )

    async def _ws_close(self) -> None:
        """
        Close the WebSocket connection.

        This method closes the WebSocket connection and logs the time
        taken for the close operation. Used during cleanup or reconnection.
        """
        start_time = datetime.now()
        await self._ws.close()
        self.ten_env.log_info(
            f"_ws_close_task done, duration:{self._duration_in_ms_since(start_time)}ms"
        )

    async def _ws_reconnect(self) -> None:
        """
        Reconnect to the WebSocket server.

        This method handles WebSocket reconnection with retry logic:
        1. Closes existing connection if any
        2. Establishes new WebSocket connection
        3. Waits for ready signal from server
        4. Retries on failure with exponential backoff

        The method uses an event to signal when the connection is ready
        for TTS operations.
        """
        self.ten_env.log_info("tencent tts _ws_reconnect start")
        self._ws_need_wait_ready_event = asyncio.Event()

        while True:
            # Check if WebSocket reconnection is allowed at the beginning of each loop iteration
            if not self._reconnect_allowed:
                self.ten_env.log_error(
                    "WebSocket reconnection disabled, stopping reconnection attempts"
                )
                break

            try:
                if self._ws != None:
                    # Call self._ws_close() immediately need several seconds, so here use create_task
                    asyncio.create_task(self._ws_close())

                self._ws = await websockets.connect(self._gen_ws_url())

                while True:
                    message = await asyncio.wait_for(self._ws.recv(), timeout=5)
                    if isinstance(message, str):
                        resp = json.loads(message)

                        if resp["code"] != 0:
                            raise TencentTTSTaskFailedException(
                                resp["code"], resp["message"]
                            )

                        if "ready" in resp and resp["ready"] == 1:
                            self._ws_need_wait_ready_event.set()
                            self._ws_need_wait_ready_event = None
                            return
                    else:
                        raise TypeError("tts resp message type is not str")

            except websockets.exceptions.ConnectionClosedOK:
                self.ten_env.log_warn(
                    "Websocket connection closed OK during TTS processing"
                )
            except websockets.exceptions.ConnectionClosed:
                self.ten_env.log_warn(
                    "Websocket connection closed during TTS processing"
                )
            except TencentTTSTaskFailedException as e:
                self.ten_env.log_error(f"_ws_reconnect tencent tts get error:{e}")

                self._reconnect_allowed = False

                if e.error_code == ERROR_CODE_AUTHORIZATION_FAILED:
                    await self.send_fatal_tts_error(e.error_msg)
                else:
                    await self.send_non_fatal_tts_error(e.error_msg)

                raise e
            except Exception as e:
                self.ten_env.log_error(f"_ws_reconnect tencent tts get error:{e}")

                await asyncio.sleep(1)  # avoid too fast retry
