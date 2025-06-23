from ten_ai_base.asr import AsyncASRBaseExtension
from ten_ai_base.transcription import UserTranscription
from ten_runtime import (
    AsyncTenEnv,
    AudioFrame,
)

import asyncio

from deepgram import (
    AsyncListenWebSocketClient,
    DeepgramClientOptions,
    LiveTranscriptionEvents,
    LiveOptions,
)
from dataclasses import dataclass

from ten_ai_base.config import BaseConfig

@dataclass
class DeepgramASRConfig(BaseConfig):
    api_key: str = ""
    language: str = "en-US"
    model: str = "nova-2"
    sample_rate: int = 16000

    channels: int = 1
    encoding: str = "linear16"
    interim_results: bool = True
    punctuate: bool = True


class DeepgramASRExtension(AsyncASRBaseExtension):
    def __init__(self, name: str):
        super().__init__(name)

        self.connected = False
        self.client: AsyncListenWebSocketClient = None
        self.config: DeepgramASRConfig = None

    async def on_init(self, ten_env: AsyncTenEnv) -> None:
        ten_env.log_info("DeepgramASRExtension on_init")

    async def start_connection(self) -> None:
        self.ten_env.log_info("start and listen deepgram")

        if self.config is None:
            self.config = await DeepgramASRConfig.create_async(ten_env=self.ten_env)
            self.ten_env.log_info(f"config: {self.config}")

            if not self.config.api_key:
                self.ten_env.log_error("get property api_key")
                return

        self.client = AsyncListenWebSocketClient(
            config=DeepgramClientOptions(
                api_key=self.config.api_key, options={"keepalive": "true"}
            )
        )

        async def on_open(_, event):
            self.ten_env.log_info(f"deepgram event callback on_open: {event}")
            self.connected = True

        async def on_close(_, event):
            self.ten_env.log_info(f"deepgram event callback on_close: {event}")
            self.connected = False
            if not self.stopped:
                self.ten_env.log_warn(
                    "Deepgram connection closed unexpectedly. Reconnecting..."
                )
                await asyncio.sleep(0.2)
                self.loop.create_task(self.start_connection())

        async def on_message(_, result):
            sentence = result.channel.alternatives[0].transcript

            if len(sentence) == 0:
                return

            is_final = result.is_final
            self.ten_env.log_info(
                f"deepgram got sentence: [{sentence}], is_final: {is_final}"
            )

            # await self._send_text(
            #     text=sentence, is_final=is_final, stream_id=self.stream_id
            # )
            transcription = UserTranscription(
                text=sentence,
                final=is_final,
                start_ms=0,
                duration_ms=100,
                language=self.config.language,
                words=[],
            )
            await self.send_asr_transcription(transcription)

        async def on_error(_, error):
            self.ten_env.log_error(f"deepgram event callback on_error: {error}")

        self.client.on(LiveTranscriptionEvents.Open, on_open)
        self.client.on(LiveTranscriptionEvents.Close, on_close)
        self.client.on(LiveTranscriptionEvents.Transcript, on_message)
        self.client.on(LiveTranscriptionEvents.Error, on_error)

        options = LiveOptions(
            language=self.config.language,
            model=self.config.model,
            sample_rate=self.config.sample_rate,
            channels=self.config.channels,
            encoding=self.config.encoding,
            interim_results=self.config.interim_results,
            punctuate=self.config.punctuate,
        )

        self.ten_env.log_info(f"deepgram options: {options}")
        # connect to websocket
        result = await self.client.start(options)
        if not result:
            self.ten_env.log_error("failed to connect to deepgram")
            await asyncio.sleep(0.2)
            self.loop.create_task(self.start_connection())
        else:
            self.ten_env.log_info("successfully connected to deepgram")

    async def stop_connection(self) -> None:
        if self.client:
            await self.client.finish()
            self.client = None
            self.connected = False
            self.ten_env.log_info("deepgram connection stopped")

    async def send_audio_frame(self, frame: AudioFrame) -> None:
        frame_buf = frame.get_buf()
        return await self.client.send(frame_buf)

    async def is_connected(self) -> bool:
        return self.connected

    async def drain(self) -> None:
        pass