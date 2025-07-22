#
# This file is part of TEN Framework, an open source project.
# Licensed under the Apache License, Version 2.0.
# See the LICENSE file for more information.
#
import asyncio
from datetime import datetime
import os
import traceback
from typing import Tuple


from ten_ai_base.helper import PCMWriter, generate_file_name
from ten_ai_base.message import (
    ModuleError,
    ModuleErrorCode,
    ModuleType,
    ModuleVendorException,
)
from ten_ai_base.struct import TTSTextInput
from ten_ai_base.tts2 import AsyncTTS2BaseExtension
from .config import BytedanceTTSDuplexConfig

from .bytedance_tts import (
    BytedanceV3Client,
    EVENT_SessionFinished,
    EVENT_TTSResponse,
)
from ten_runtime import (
    AsyncTenEnv,
)


class BytedanceTTSDuplexExtension(AsyncTTS2BaseExtension):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.config: BytedanceTTSDuplexConfig = None
        self.client: BytedanceV3Client = None
        self.current_request_id: str = None
        self.current_turn_id: int = -1
        self.stop_event: asyncio.Event = None
        self.msg_polling_task: asyncio.Task = None
        self.recorder: PCMWriter = None
        self.sent_ts: datetime | None = None
        self.response_msgs = asyncio.Queue[Tuple[int, bytes]]()

    async def on_init(self, ten_env: AsyncTenEnv) -> None:
        try:
            await super().on_init(ten_env)
            ten_env.log_debug("on_init")

            if self.config is None:
                config_json, _ = await self.ten_env.get_property_to_json("")
                self.config = BytedanceTTSDuplexConfig.model_validate_json(
                    config_json
                )
                self.ten_env.log_debug(f"config: {self.config}")

                if not self.config.appid:
                    self.ten_env.log_error("get property appid")
                    return ValueError("appid is required")

                if not self.config.token:
                    self.ten_env.log_error("get property token")
                    return ValueError("token is required")

                # extract audio_params and additions from config
                self.config.update_params()

            self.recorder = PCMWriter(
                os.path.join(
                    self.config.dump_path, generate_file_name("agent_dump")
                )
                # based on request id
            )

            await self._start_connection()
            self.msg_polling_task = asyncio.create_task(self._loop())
        except Exception as e:
            ten_env.log_error(f"on_start failed: {traceback.format_exc()}")
            await self.send_tts_error(
                self.current_request_id,
                ModuleError(
                    message=str(e),
                    module_name=ModuleType.ASR,
                    code=ModuleErrorCode.FATAL_ERROR,
                    vendor_info=None,
                ),
            )

    async def on_stop(self, ten_env: AsyncTenEnv) -> None:
        await self._stop_connection()
        if self.msg_polling_task:
            self.msg_polling_task.cancel()
        await super().on_stop(ten_env)
        ten_env.log_debug("on_stop")

    async def on_deinit(self, ten_env: AsyncTenEnv) -> None:
        await super().on_deinit(ten_env)
        ten_env.log_debug("on_deinit")

    async def _loop(self) -> None:
        while True:
            try:
                event, audio_data = await self.client.response_msgs.get()
                self.ten_env.log_debug(f"Received event: {event}")

                if event == EVENT_TTSResponse:
                    if audio_data is not None:
                        if self.config.dump:
                            asyncio.create_task(self.recorder.write(audio_data))
                        if self.sent_ts is not None:
                            elapsed_time = int(
                                (datetime.now() - self.sent_ts).total_seconds()
                                * 1000
                            )
                            await self.send_tts_ttfb_metrics(
                                self.current_request_id,
                                elapsed_time,
                                self.current_turn_id,
                            )
                            self.sent_ts = None
                            self.ten_env.log_info(
                                f"Sent TTFB metrics for request ID: {self.current_request_id}, elapsed time: {elapsed_time}ms"
                            )
                        await self.send_tts_audio_data(audio_data)
                    else:
                        self.ten_env.log_error(
                            "Received empty payload for TTS response"
                        )
                elif event == EVENT_SessionFinished:
                    self.ten_env.log_info(
                        f"Session finished for request ID: {self.current_request_id}"
                    )
                    if self.stop_event:
                        self.stop_event.set()
                        self.stop_event = None

            except Exception:
                self.ten_env.log_error(
                    f"Error in _loop: {traceback.format_exc()}"
                )

    async def _start_connection(self) -> None:
        """
        Prepare the connection to the TTS service.
        This method is called before sending any TTS requests.
        """
        if self.client is None:
            self.client = BytedanceV3Client(
                self.config, self.ten_env, self.vendor(), self.response_msgs
            )
            self.ten_env.log_info("KEYPOINT Connecting to service")
            await self.client.connect()
            await self.client.start_connection()
            await self.client.start_session()

    async def _stop_connection(self) -> None:
        try:
            if self.client:
                await self.client.finish_session()
                await self.client.finish_connection()
                await self.client.close()
        except Exception:
            self.ten_env.log_warn(
                f"Error during cleanup: {traceback.format_exc()}"
            )
        if self.stop_event:
            self.stop_event.set()
            self.stop_event = None
        self.client = None

    async def _reconnect(self) -> None:
        """
        Reconnect to the TTS service.
        This method is called when the connection is lost or needs to be re-established.
        """
        await self._stop_connection()
        await self._start_connection()

    def vendor(self) -> str:
        return "bytedance"

    def synthesize_audio_sample_rate(self) -> int:
        return self.config.sample_rate

    async def request_tts(self, t: TTSTextInput) -> None:
        """
        Override this method to handle TTS requests.
        This is called when the TTS request is made.
        """
        try:
            self.ten_env.log_info(
                f"KEYPOINT Requesting TTS for text: {t.text}, text_input_end: {t.text_input_end} request ID: {t.request_id}"
            )
            if t.request_id != self.current_request_id:
                self.ten_env.log_info(
                    f"New TTS request with ID: {t.request_id}"
                )
                self.current_request_id = t.request_id
                if t.metadata is not None:
                    self.session_id = t.metadata.session_id
                    self.current_turn_id = t.metadata.turn_id
                if self.sent_ts is None:
                    self.sent_ts = datetime.now()

            if t.text.strip() != "":
                await self.client.send_text(t.text)
            if t.text_input_end:
                self.ten_env.log_info(
                    f"KEYPOINT finish session for request ID: {t.request_id}"
                )
                await self.client.finish_session()

                self.stop_event = asyncio.Event()
                await self.stop_event.wait()

                # close connection after session is finished
                await self.client.finish_connection()
                await self.client.close()
                self.client = None

                # restart connection to prepare for the next request
                await self._start_connection()
        except ModuleVendorException as e:
            self.ten_env.log_error(
                f"ModuleVendorException in request_tts: {traceback.format_exc()}. text: {t.text}"
            )
            await self.send_tts_error(
                self.current_request_id,
                ModuleError(
                    message=str(e),
                    module_name=ModuleType.TTS,
                    code=ModuleErrorCode.NON_FATAL_ERROR,
                    vendor_info=e.error,
                ),
            )
            await self._reconnect()
        except Exception as e:
            self.ten_env.log_error(
                f"Error in request_tts: {traceback.format_exc()}. text: {t.text}"
            )
            await self.send_tts_error(
                self.current_request_id,
                ModuleError(
                    message=str(e),
                    module_name=ModuleType.TTS,
                    code=ModuleErrorCode.NON_FATAL_ERROR,
                    vendor_info=None,
                ),
            )
            await self._reconnect()
