import sys
from pathlib import Path

# Add project root to sys.path to allow running tests from this directory
# The project root is 6 levels up from the parent directory of this file.
project_root = str(Path(__file__).resolve().parents[6])
if project_root not in sys.path:
    sys.path.insert(0, project_root)

#
# Copyright © 2024 Agora
# This file is part of TEN Framework, an open source project.
# Licensed under the Apache License, Version 2.0, with certain conditions.
# Refer to the "LICENSE" file in the root directory for more information.
#
import json
import asyncio
from typing import Any
from unittest.mock import patch, AsyncMock, MagicMock

from ten_runtime import (
    ExtensionTester,
    TenEnvTester,
    Data,
)
from ten_ai_base.struct import TTSTextInput
from ..tencent_tts import (
    TencentTTSTaskFailedException,
    TencentTTSClient,
)


class TestTencentTTSRobustness:
    """Robustness and error recovery tests for Tencent TTS extension"""

    @patch("websockets.connect")
    def test_reconnect_after_connection_drop(self, mock_ws_connect):
        """Test that the extension can recover from WebSocket connection drops"""
        # First call fails, second call succeeds
        mock_ws_connect.side_effect = [
            ConnectionRefusedError("Simulated connection drop"),
            MagicMock(),  # Successful connection
        ]

        config = {
            "app_id": "test_app",
            "secret_id": "test_secret_id",
            "secret_key": "test_secret_key",
        }

        tester = RobustnessTester()
        tester.set_test_mode_single("tencent_tts_python", json.dumps(config))

        tester.run()

        # Verify error handling and recovery
        assert (
            tester.connection_error_received
        ), "Should handle connection error"
        assert (
            tester.recovery_successful
        ), "Should recover after connection error"


class RobustnessTester(ExtensionTester):
    """Robustness testing for connection failures and recovery"""

    def __init__(self):
        super().__init__()
        self.connection_error_received = False
        self.recovery_successful = False
        self.error_details = None

    def on_start(self, ten_env_tester: TenEnvTester) -> None:
        """Start robustness test"""
        ten_env_tester.log_info("Starting robustness test")

        tts_input = TTSTextInput(
            request_id="robustness_test_request",
            text="Test text for robustness testing",
            text_input_end=True,
        )

        data = Data.create("tts_text_input")
        data.set_property_from_json(None, tts_input.model_dump_json())
        ten_env_tester.send_data(data)
        ten_env_tester.on_start_done()

    def on_data(self, ten_env: TenEnvTester, data) -> None:
        """Handle test events"""
        name = data.get_name()

        if name == "error":
            self.connection_error_received = True
            json_str, _ = data.get_property_to_json(None)
            if json_str:
                self.error_details = json.loads(json_str)
            ten_env.log_info(f"Connection error received: {self.error_details}")

            # Send retry request
            self.send_retry_request(ten_env)
        elif name == "tts_audio_end":
            self.recovery_successful = True
            ten_env.log_info("Recovery successful - TTS completed")
            ten_env.stop_test()

    def send_retry_request(self, ten_env: TenEnvTester):
        """Send retry request after connection error"""
        ten_env.log_info("Sending retry request")

        retry_input = TTSTextInput(
            request_id="robustness_retry_request",
            text="Retry text for robustness testing",
            text_input_end=True,
        )

        data = Data.create("tts_text_input")
        data.set_property_from_json(None, retry_input.model_dump_json())
        ten_env.send_data(data)


class TestTencentTTSRateLimiting:
    """Rate limiting and throttling tests"""

    @patch("websockets.connect")
    def test_rate_limit_handling(self, mock_ws_connect):
        """Test handling of rate limiting responses"""
        # Mock rate limit response
        mock_ws = MagicMock()
        mock_ws_connect.return_value = mock_ws

        # Simulate rate limit error
        mock_ws.recv = AsyncMock(
            return_value=json.dumps(
                {"type": "error", "code": 429, "message": "Rate limit exceeded"}
            )
        )

        config = {
            "app_id": "test_app",
            "secret_id": "test_secret_id",
            "secret_key": "test_secret_key",
        }

        tester = RateLimitTester()
        tester.set_test_mode_single("tencent_tts_python", json.dumps(config))

        tester.run()

        assert (
            tester.rate_limit_error_received
        ), "Should handle rate limit errors"


class RateLimitTester(ExtensionTester):
    """Rate limiting test handler"""

    def __init__(self):
        super().__init__()
        self.rate_limit_error_received = False
        self.error_code = None

    def on_start(self, ten_env_tester: TenEnvTester) -> None:
        """Start rate limit test"""
        ten_env_tester.log_info("Starting rate limit test")

        tts_input = TTSTextInput(
            request_id="rate_limit_test_request",
            text="Test text for rate limiting",
            text_input_end=True,
        )

        data = Data.create("tts_text_input")
        data.set_property_from_json(None, tts_input.model_dump_json())
        ten_env_tester.send_data(data)
        ten_env_tester.on_start_done()

    def on_data(self, ten_env: TenEnvTester, data) -> None:
        """Handle rate limit events"""
        name = data.get_name()

        if name == "error":
            json_str, _ = data.get_property_to_json(None)
            if json_str:
                error_data = json.loads(json_str)
                if error_data.get("code") == 429:
                    self.rate_limit_error_received = True
                    self.error_code = error_data.get("code")
                    ten_env.log_info(f"Rate limit error received: {error_data}")
                    ten_env.stop_test()


class TestTencentTTSNetworkInstability:
    """Network instability and timeout tests"""

    @patch("websockets.connect")
    def test_timeout_handling(self, mock_ws_connect):
        """Test handling of network timeouts"""
        # Mock timeout behavior
        mock_ws = MagicMock()
        mock_ws_connect.return_value = mock_ws

        # Simulate timeout
        mock_ws.recv = AsyncMock(
            side_effect=asyncio.TimeoutError("Connection timeout")
        )

        config = {
            "app_id": "test_app",
            "secret_id": "test_secret_id",
            "secret_key": "test_secret_key",
        }

        tester = TimeoutTester()
        tester.set_test_mode_single("tencent_tts_python", json.dumps(config))

        tester.run()

        assert tester.timeout_error_received, "Should handle timeout errors"


class TimeoutTester(ExtensionTester):
    """Timeout test handler"""

    def __init__(self):
        super().__init__()
        self.timeout_error_received = False

    def on_start(self, ten_env_tester: TenEnvTester) -> None:
        """Start timeout test"""
        ten_env_tester.log_info("Starting timeout test")

        tts_input = TTSTextInput(
            request_id="timeout_test_request",
            text="Test text for timeout testing",
            text_input_end=True,
        )

        data = Data.create("tts_text_input")
        data.set_property_from_json(None, tts_input.model_dump_json())
        ten_env_tester.send_data(data)
        ten_env_tester.on_start_done()

    def on_data(self, ten_env: TenEnvTester, data) -> None:
        """Handle timeout events"""
        name = data.get_name()

        if name == "error":
            self.timeout_error_received = True
            json_str, _ = data.get_property_to_json(None)
            if json_str:
                error_data = json.loads(json_str)
                ten_env.log_info(f"Timeout error received: {error_data}")
                ten_env.stop_test()
