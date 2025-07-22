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
        self.client: BytedanceV3Client = None
        self.current_request_id: str = None
        self.current_turn_id: int = -1
        self.stop_event: asyncio.Event = None
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

            self.recorder = PCMWriter(
                os.path.join(
                    self.config.dump_path, generate_file_name("agent_dump")
                )
            )
            self.client = BytedanceV3Client(self.config, ten_env)
        except Exception:
            ten_env.log_error(f"on_start failed: {traceback.format_exc()}")

    async def on_stop(self, ten_env: AsyncTenEnv) -> None:
        if self.client:
            await self.client.close()

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
            if t.request_id != self.current_request_id:
                self.ten_env.log_info(
                    f"New TTS request with ID: {t.request_id}"
                )
                self.current_request_id = t.request_id
                if t.metadata is not None:
                    self.session_id = t.metadata.session_id
                    self.current_turn_id = t.metadata.turn_id
                self.sent_ts = None
                await self.client.finish_session()
                await self.client.finish_connection()
                await self.client.close()

                if self.sent_ts is None:
                    self.sent_ts = datetime.now()

                self.client = BytedanceV3Client(self.config, self.ten_env)
                await self.client.connect()

                asyncio.create_task(self._loop())

                await self.client.start_connection()
                await self.client.start_session()

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

        except Exception:
            self.ten_env.log_error(
                f"Error in request_tts: {traceback.format_exc()}"
            )
            # yield b""

        # self.ten_env.log_info("TTS request completed")
