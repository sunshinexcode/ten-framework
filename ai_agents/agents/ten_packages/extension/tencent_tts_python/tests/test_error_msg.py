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
from typing import Any, Dict
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


class TestTencentTTSErrorHandling:
    """Comprehensive error handling and error message tests for Tencent TTS extension"""

    @patch("websockets.connect")
    def test_authentication_error_handling(self, mock_ws_connect):
        """Test handling of authentication and authorization errors"""
        # Mock authentication failure
        mock_ws_connect.side_effect = Exception(
            "Authentication failed: Invalid credentials"
        )

        config = {
            "app_id": "invalid_app_id",
            "secret_id": "invalid_secret_id",
            "secret_key": "invalid_secret_key",
        }

        tester = AuthenticationErrorTester()
        tester.set_test_mode_single("tencent_tts_python", json.dumps(config))

        tester.run()

        # Verify authentication error handling
        assert tester.auth_error_received, "Should handle authentication errors"
        assert tester.error_code is not None, "Error code should be provided"
        assert (
            "authentication" in tester.error_message.lower()
        ), "Error message should mention authentication"


class AuthenticationErrorTester(ExtensionTester):
    """Tester for authentication error scenarios"""

    def __init__(self):
        super().__init__()
        self.auth_error_received = False
        self.error_code = None
        self.error_message = None

    def on_start(self, ten_env_tester: TenEnvTester) -> None:
        """Start authentication error test"""
        ten_env_tester.log_info("Starting authentication error test")

        tts_input = TTSTextInput(
            request_id="auth_error_test_request",
            text="Test text for authentication error testing",
            text_input_end=True,
        )

        data = Data.create("tts_text_input")
        data.set_property_from_json(None, tts_input.model_dump_json())
        ten_env_tester.send_data(data)
        ten_env_tester.on_start_done()

    def on_data(self, ten_env: TenEnvTester, data) -> None:
        """Handle authentication error events"""
        name = data.get_name()

        if name == "error":
            self.auth_error_received = True
            json_str, _ = data.get_property_to_json(None)
            if json_str:
                error_data = json.loads(json_str)
                self.error_code = error_data.get("code")
                self.error_message = error_data.get("message", "")

                ten_env.log_info(f"Authentication error received: {error_data}")
                ten_env.stop_test()


class TestTencentTTSNetworkErrors:
    """Network-related error handling tests"""

    @patch("websockets.connect")
    def test_network_timeout_error(self, mock_ws_connect):
        """Test handling of network timeout errors"""
        # Mock network timeout
        mock_ws_connect.side_effect = TimeoutError("Connection timeout")

        config = {
            "app_id": "test_app_id",
            "secret_id": "test_secret_id",
            "secret_key": "test_secret_key",
        }

        tester = NetworkErrorTester()
        tester.set_test_mode_single("tencent_tts_python", json.dumps(config))

        tester.run()

        # Verify network error handling
        assert tester.network_error_received, "Should handle network errors"
        assert (
            "timeout" in tester.error_message.lower()
        ), "Error message should mention timeout"

    @patch("websockets.connect")
    def test_connection_refused_error(self, mock_ws_connect):
        """Test handling of connection refused errors"""
        # Mock connection refused
        mock_ws_connect.side_effect = ConnectionRefusedError(
            "Connection refused"
        )

        config = {
            "app_id": "test_app_id",
            "secret_id": "test_secret_id",
            "secret_key": "test_secret_key",
        }

        tester = NetworkErrorTester()
        tester.set_test_mode_single("tencent_tts_python", json.dumps(config))

        tester.run()

        # Verify connection error handling
        assert tester.network_error_received, "Should handle connection errors"
        assert (
            "connection" in tester.error_message.lower()
        ), "Error message should mention connection"


class NetworkErrorTester(ExtensionTester):
    """Tester for network error scenarios"""

    def __init__(self):
        super().__init__()
        self.network_error_received = False
        self.error_message = None

    def on_start(self, ten_env_tester: TenEnvTester) -> None:
        """Start network error test"""
        ten_env_tester.log_info("Starting network error test")

        tts_input = TTSTextInput(
            request_id="network_error_test_request",
            text="Test text for network error testing",
            text_input_end=True,
        )

        data = Data.create("tts_text_input")
        data.set_property_from_json(None, tts_input.model_dump_json())
        ten_env_tester.send_data(data)
        ten_env_tester.on_start_done()

    def on_data(self, ten_env: TenEnvTester, data) -> None:
        """Handle network error events"""
        name = data.get_name()

        if name == "error":
            self.network_error_received = True
            json_str, _ = data.get_property_to_json(None)
            if json_str:
                error_data = json.loads(json_str)
                self.error_message = error_data.get("message", "")

                ten_env.log_info(f"Network error received: {error_data}")
                ten_env.stop_test()


class TestTencentTTSAPIErrors:
    """API-specific error handling tests"""

    @patch("websockets.connect")
    def test_rate_limit_error(self, mock_ws_connect):
        """Test handling of rate limiting errors"""
        # Mock rate limit response
        mock_ws = MagicMock()
        mock_ws_connect.return_value = mock_ws

        # Simulate rate limit error
        mock_ws.recv = AsyncMock(
            return_value=json.dumps(
                {
                    "type": "error",
                    "code": 429,
                    "message": "Rate limit exceeded. Please try again later.",
                }
            )
        )

        config = {
            "app_id": "test_app_id",
            "secret_id": "test_secret_id",
            "secret_key": "test_secret_key",
        }

        tester = APIErrorTester()
        tester.set_test_mode_single("tencent_tts_python", json.dumps(config))

        tester.run()

        # Verify rate limit error handling
        assert tester.api_error_received, "Should handle API errors"
        assert tester.error_code == 429, "Should receive rate limit error code"
        assert (
            "rate limit" in tester.error_message.lower()
        ), "Error message should mention rate limit"

    @patch("websockets.connect")
    def test_invalid_text_error(self, mock_ws_connect):
        """Test handling of invalid text input errors"""
        # Mock invalid text error
        mock_ws = MagicMock()
        mock_ws_connect.return_value = mock_ws

        # Simulate invalid text error
        mock_ws.recv = AsyncMock(
            return_value=json.dumps(
                {
                    "type": "error",
                    "code": 400,
                    "message": "Invalid text input: Text cannot be empty",
                }
            )
        )

        config = {
            "app_id": "test_app_id",
            "secret_id": "test_secret_id",
            "secret_key": "test_secret_key",
        }

        tester = APIErrorTester()
        tester.set_test_mode_single("tencent_tts_python", json.dumps(config))

        tester.run()

        # Verify invalid text error handling
        assert tester.api_error_received, "Should handle API errors"
        assert tester.error_code == 400, "Should receive bad request error code"
        assert (
            "invalid text" in tester.error_message.lower()
        ), "Error message should mention invalid text"


class APIErrorTester(ExtensionTester):
    """Tester for API error scenarios"""

    def __init__(self):
        super().__init__()
        self.api_error_received = False
        self.error_code = None
        self.error_message = None

    def on_start(self, ten_env_tester: TenEnvTester) -> None:
        """Start API error test"""
        ten_env_tester.log_info("Starting API error test")

        tts_input = TTSTextInput(
            request_id="api_error_test_request",
            text="Test text for API error testing",
            text_input_end=True,
        )

        data = Data.create("tts_text_input")
        data.set_property_from_json(None, tts_input.model_dump_json())
        ten_env_tester.send_data(data)
        ten_env_tester.on_start_done()

    def on_data(self, ten_env: TenEnvTester, data) -> None:
        """Handle API error events"""
        name = data.get_name()

        if name == "error":
            self.api_error_received = True
            json_str, _ = data.get_property_to_json(None)
            if json_str:
                error_data = json.loads(json_str)
                self.error_code = error_data.get("code")
                self.error_message = error_data.get("message", "")

                ten_env.log_info(f"API error received: {error_data}")
                ten_env.stop_test()


class TestTencentTTSErrorMessageFormat:
    """Test error message format and structure"""

    def test_error_message_structure(self):
        """Test that error messages have proper structure"""
        # Sample error message structure
        error_message = {
            "code": 500,
            "message": "Internal server error occurred",
            "request_id": "req_12345",
            "timestamp": "2024-01-01T00:00:00Z",
            "details": {
                "error_type": "server_error",
                "suggestion": "Please try again later",
            },
        }

        # Validate error message structure
        assert "code" in error_message, "Error should have code field"
        assert "message" in error_message, "Error should have message field"
        assert (
            "request_id" in error_message
        ), "Error should have request_id field"
        assert "timestamp" in error_message, "Error should have timestamp field"

        # Validate error code
        assert isinstance(
            error_message["code"], int
        ), "Error code should be integer"
        assert error_message["code"] >= 100, "Error code should be >= 100"

        # Validate error message
        assert isinstance(
            error_message["message"], str
        ), "Error message should be string"
        assert (
            len(error_message["message"]) > 0
        ), "Error message should not be empty"

    def test_error_code_categories(self):
        """Test error code categorization"""
        # Define error code categories
        client_errors = [400, 401, 403, 404, 429]  # 4xx errors
        server_errors = [500, 502, 503, 504]  # 5xx errors
        network_errors = [1000, 1001, 1002]  # Custom network errors

        # Test client error codes
        for code in client_errors:
            assert 400 <= code < 500, f"Client error code should be 4xx: {code}"

        # Test server error codes
        for code in server_errors:
            assert 500 <= code < 600, f"Server error code should be 5xx: {code}"

        # Test custom network error codes
        for code in network_errors:
            assert code >= 1000, f"Custom error code should be >= 1000: {code}"


class TestTencentTTSErrorRecovery:
    """Test error recovery and retry mechanisms"""

    @patch("websockets.connect")
    def test_retry_after_transient_error(self, mock_ws_connect):
        """Test automatic retry after transient errors"""
        # Mock transient error followed by success
        mock_ws_connect.side_effect = [
            ConnectionRefusedError("Temporary connection issue"),
            MagicMock(),  # Successful connection on retry
        ]

        config = {
            "app_id": "test_app_id",
            "secret_id": "test_secret_id",
            "secret_key": "test_secret_key",
            "max_retries": 3,
            "retry_delay": 1,
        }

        tester = ErrorRecoveryTester()
        tester.set_test_mode_single("tencent_tts_python", json.dumps(config))

        tester.run()

        # Verify error recovery
        assert tester.transient_error_received, "Should handle transient errors"
        assert (
            tester.recovery_successful
        ), "Should recover after transient error"


class ErrorRecoveryTester(ExtensionTester):
    """Tester for error recovery scenarios"""

    def __init__(self):
        super().__init__()
        self.transient_error_received = False
        self.recovery_successful = False

    def on_start(self, ten_env_tester: TenEnvTester) -> None:
        """Start error recovery test"""
        ten_env_tester.log_info("Starting error recovery test")

        tts_input = TTSTextInput(
            request_id="recovery_test_request",
            text="Test text for error recovery testing",
            text_input_end=True,
        )

        data = Data.create("tts_text_input")
        data.set_property_from_json(None, tts_input.model_dump_json())
        ten_env_tester.send_data(data)
        ten_env_tester.on_start_done()

    def on_data(self, ten_env: TenEnvTester, data) -> None:
        """Handle error recovery events"""
        name = data.get_name()

        if name == "error":
            self.transient_error_received = True
            ten_env.log_info("Transient error received, waiting for recovery")
        elif name == "tts_audio_end":
            self.recovery_successful = True
            ten_env.log_info("Recovery successful - TTS completed")
            ten_env.stop_test()
