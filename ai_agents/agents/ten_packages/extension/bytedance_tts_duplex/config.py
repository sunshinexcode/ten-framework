from typing import Any, Dict

from pydantic import BaseModel, Field


class BytedanceTTSDuplexConfig(BaseModel):
    appid: str
    token: str

    # Refer to: https://www.volcengine.com/docs/6561/1257544.
    voice_type: str = "zh_female_shuangkuaisisi_moon_bigtts"
    sample_rate: int = 24000
    api_url: str = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
    dump: bool = False
    dump_path: str = "/tmp"
    params: Dict[str, Any] = Field(default_factory=dict)
    enable_words: bool = False

    def update_params(self) -> None:
        ##### get value from params #####
        if (
            "audio_params" in self.params
            and "sample_rate" in self.params["audio_params"]
        ):
            self.sample_rate = int(self.params["audio_params"]["sample_rate"])

        if (
            "audio_params" not in self.params
            or "sample_rate" not in self.params["audio_params"]
        ):
            if "audio_params" not in self.params:
                self.params["audio_params"] = {}
            self.params["audio_params"]["sample_rate"] = self.sample_rate

        ##### use fixed value #####
        if "audio_params" not in self.params:
            self.params["audio_params"] = {}
        self.params["audio_params"]["format"] = "pcm"
