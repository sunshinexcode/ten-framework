from typing import Any, Dict
from pydantic import BaseModel, Field


def mask_sensitive_data(
    s: str, unmasked_start: int = 3, unmasked_end: int = 3, mask_char: str = "*"
) -> str:
    """
    Mask a sensitive string by replacing the middle part with asterisks.

    Parameters:
        s (str): The input string (e.g., API key).
        unmasked_start (int): Number of visible characters at the beginning.
        unmasked_end (int): Number of visible characters at the end.
        mask_char (str): Character used for masking.

    Returns:
        str: Masked string, e.g., "abc****xyz"
    """
    if not s or len(s) <= unmasked_start + unmasked_end:
        return mask_char * len(s)

    return (
        s[:unmasked_start]
        + mask_char * (len(s) - unmasked_start - unmasked_end)
        + s[-unmasked_end:]
    )


class CosyTTSConfig(BaseModel):
    # Cosy TTS credentials
    api_key: str = ""  # Cosy TTS API Key

    # TTS specific configs
    model: str = "cosyvoice-v1"  # Model name
    sample_rate: int = 16000  # Audio sample rate
    voice: str = "longxiaochun"  # Voice name

    # Debug and dump settings
    dump: bool = False
    dump_path: str = "/tmp"

    # Parameters
    params: dict[str, Any] = Field(default_factory=dict)

    def update_params(self) -> None:
        """Update config attributes from params dictionary."""
        # Handle api_key parameter
        if "api_key" in self.params:
            self.api_key = self.params["api_key"]
            del self.params["api_key"]

        # Handle model parameter
        if "model" in self.params:
            self.model = self.params["model"]
            del self.params["model"]

        # Handle sample_rate parameter
        if "sample_rate" in self.params:
            self.sample_rate = self.params["sample_rate"]
            del self.params["sample_rate"]

        # Handle voice parameter
        if "voice" in self.params:
            self.voice = self.params["voice"]
            del self.params["voice"]

    def to_str(self) -> str:
        """
        Convert the configuration to a string representation, masking sensitive data.
        """
        return (
            f"CosyTTSConfig(api_key={mask_sensitive_data(self.api_key)}, "
            f"model='{self.model}', "
            f"sample_rate='{self.sample_rate}', "
            f"voice='{self.voice}', "
            f"dump='{self.dump}', "
            f"dump_path='{self.dump_path}', "
            f"params={self.params}, "
        )
