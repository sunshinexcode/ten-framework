#
# This file is part of TEN Framework, an open source project.
# Licensed under the Apache License, Version 2.0.
# See the LICENSE file for more information.
#
import asyncio
from datetime import datetime
import os
import traceback


from ten_ai_base.helper import PCMWriter, generate_file_name
from ten_ai_base.message import (
    ModuleError,
    ModuleErrorCode,
    ModuleType,
    ModuleVendorException,
)
from ten_ai_base.struct import TTSTextInput
from ten_ai_base.tts2 import AsyncTTS2BaseExtension

from .bytedance_tts import (
    BytedanceTTSDuplexConfig,
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
        self.stopped: bool = False
        self.client: BytedanceV3Client = None
        self.current_request_id: str = None
        self.current_turn_id: int = -1
        self.stop_event: asyncio.Event = None
        self.msg_polling_task: asyncio.Task = None
        self.recorder: PCMWriter = None
        self.sent_ts: datetime | None = None

    async def on_start(self, ten_env: AsyncTenEnv) -> None:
        try:
            await super().on_start(ten_env)
            ten_env.log_debug("on_start")

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
            )
            self.client = BytedanceV3Client(self.config, ten_env, self.vendor())
        except Exception as e:
            ten_env.log_error(f"on_start failed: {traceback.format_exc()}")
            await self.send_tts_error(
                self.current_request_id,
                ModuleError(
                    message=e,
                    module_name=ModuleType.ASR,
                    code=ModuleErrorCode.FATAL_ERROR,
                    vendor_info=None,
                ),
            )

    async def on_stop(self, ten_env: AsyncTenEnv) -> None:
        if self.client:
            await self.client.close()

        self.stopped = True
        await super().on_stop(ten_env)
        ten_env.log_debug("on_stop")

    async def on_deinit(self, ten_env: AsyncTenEnv) -> None:
        await super().on_deinit(ten_env)
        ten_env.log_debug("on_deinit")

    async def _loop(self) -> None:
        while self.stopped is False:
            try:
                event, audio_data = await self.client.response_msgs.get()
                self.ten_env.log_debug(f"Received event: {event}")

                if event == EVENT_TTSResponse:
                    if audio_data is not None:
                        if self.config.dump:
                            asyncio.create_task(self.recorder.write(audio_data))
                        if self.sent_ts is not None:
                            elapsed_time = datetime.now() - self.sent_ts
                            await self.send_tts_ttfb_metrics(
                                self.current_request_id,
                                elapsed_time,
                                self.current_turn_id,
                            )
                            self.sent_ts = None
                            self.ten_env.log_info(
                                f"Sent TTFB metrics for request ID: {self.current_request_id}, elapsed time: {elapsed_time}"
                            )
                        await self.send_tts_audio_data(audio_data)
                    else:
                        self.ten_env.log_error(
                            "Received empty payload for TTS response"
                        )
                elif event == EVENT_SessionFinished:
                    if self.stop_event:
                        self.stop_event.set()
                        self.stop_event = None
                    break

            except Exception:
                self.ten_env.log_error(
                    f"Error in _loop: {traceback.format_exc()}"
                )
                break

    async def _cleanup(self) -> None:
        try:
            if self.msg_polling_task:
                self.msg_polling_task.cancel()
        except Exception:
            self.ten_env.log_warn(
                f"Error cancelling msg_polling_task: {traceback.format_exc()}"
            )
        try:
            if self.client:
                await self.client.finish_session()
                await self.client.finish_connection()
                await self.client.close()
        except Exception:
            self.ten_env.log_warn(
                f"Error during cleanup: {traceback.format_exc()}"
            )
        self.client = None
        self.msg_polling_task = None

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
            if t.text.strip() == "":
                self.ten_env.log_info("Received empty text for TTS request")
                return
            if t.request_id != self.current_request_id or self.client is None:
                self.ten_env.log_info(
                    f"New TTS request with ID: {t.request_id}"
                )
                self.current_request_id = t.request_id
                if t.metadata is not None:
                    self.session_id = t.metadata.session_id
                    self.current_turn_id = t.metadata.turn_id
                self.sent_ts = None
                await self._cleanup()

                if self.sent_ts is None:
                    self.sent_ts = datetime.now()

                self.client = BytedanceV3Client(
                    self.config, self.ten_env, self.vendor()
                )
                await self.client.connect()

                await self.client.start_connection()
                await self.client.start_session()

                self.msg_polling_task = asyncio.create_task(self._loop())

            await self.client.send_text(t.text)
            if t.text_input_end:
                self.ten_env.log_info(
                    f"Received TTS text input end for request ID: {t.request_id}"
                )
                await self.client.finish_session()

                self.stop_event = asyncio.Event()
                await self.stop_event.wait()

                await self.client.finish_connection()
                await self.client.close()
                self.client = None
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
            await self._cleanup()
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
            await self._cleanup()
