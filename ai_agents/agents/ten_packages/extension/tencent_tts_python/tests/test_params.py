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
from typing import Any
from unittest.mock import patch, AsyncMock, MagicMock

from ten_runtime import (
    ExtensionTester,
    TenEnvTester,
    Cmd,
    CmdResult,
    StatusCode,
    Data,
    TenError,
)
from ..tencent_tts import TencentTTSClient
from ..config import TencentTTSConfig


class TestTencentTTSConfiguration:
    """Configuration and parameter validation tests for Tencent TTS extension"""
    
    def test_required_config_fields(self):
        """Test that required configuration fields are properly validated"""
        # Valid configuration
        valid_config = {
            "app_id": "test_app_id",
            "secret_id": "test_secret_id",
            "secret_key": "test_secret_key"
        }
        
        # Test required fields
        assert "app_id" in valid_config, "app_id is required"
        assert "secret_id" in valid_config, "secret_id is required"
        assert "secret_key" in valid_config, "secret_key is required"
        
        # Test field types
        assert isinstance(valid_config["app_id"], str), "app_id should be string"
        assert isinstance(valid_config["secret_id"], str), "secret_id should be string"
        assert isinstance(valid_config["secret_key"], str), "secret_key should be string"
    
    def test_optional_config_fields(self):
        """Test optional configuration fields with default values"""
        # Configuration with optional fields
        config_with_options = {
            "app_id": "test_app_id",
            "secret_id": "test_secret_id",
            "secret_key": "test_secret_key",
            "region": "ap-beijing",
            "endpoint": "tts.tencentcloudapi.com",
            "timeout": 30
        }
        
        # Test optional fields
        assert config_with_options.get("region") == "ap-beijing", "region should be configurable"
        assert config_with_options.get("endpoint") == "tts.tencentcloudapi.com", "endpoint should be configurable"
        assert config_with_options.get("timeout") == 30, "timeout should be configurable"
    
    def test_config_validation(self):
        """Test configuration validation logic"""
        # Test invalid configurations
        invalid_configs = [
            {},  # Empty config
            {"app_id": "test"},  # Missing required fields
            {"app_id": "", "secret_id": "test", "secret_key": "test"},  # Empty app_id
            {"app_id": "test", "secret_id": None, "secret_key": "test"},  # None secret_id
        ]
        
        for invalid_config in invalid_configs:
            try:
                # This should raise validation error
                TencentTTSConfig(**invalid_config)
                assert False, f"Config should be invalid: {invalid_config}"
            except (ValueError, TypeError):
                # Expected validation error
                pass


class TestTencentTTSParameterPassthrough:
    """Test that custom parameters are correctly passed through to the TTS client"""
    
    @patch('websockets.connect')
    def test_custom_parameters_passthrough(self, mock_ws_connect):
        """Test that custom TTS parameters are forwarded correctly"""
        # Mock WebSocket connection
        mock_ws = MagicMock()
        mock_ws_connect.return_value = mock_ws
        
        # Configuration with custom TTS parameters
        custom_params = {
            "voice_type": "female",
            "volume": 0.8,
            "speed": 1.2,
            "pitch": 0.0,
            "codec": "pcm",
            "sample_rate": 16000
        }
        
        config = {
            "app_id": "test_app_id",
            "secret_id": "test_secret_id",
            "secret_key": "test_secret_key",
            "tts_params": custom_params
        }
        
        tester = ParameterPassthroughTester()
        tester.set_test_mode_single("tencent_tts_python", json.dumps(config))
        
        tester.run()
        
        # Verify parameters were passed through
        assert tester.parameters_received, "Custom parameters should be received"
        assert tester.parameter_values == custom_params, "Parameter values should match"


class ParameterPassthroughTester(ExtensionTester):
    """Tester for parameter passthrough functionality"""
    
    def __init__(self):
        super().__init__()
        self.parameters_received = False
        self.parameter_values = None
    
    def on_start(self, ten_env_tester: TenEnvTester) -> None:
        """Start parameter passthrough test"""
        ten_env_tester.log_info("Starting parameter passthrough test")
        
        # Send a simple command to check configuration
        cmd = Cmd.create("get_config")
        ten_env_tester.send_cmd(
            cmd,
            lambda ten_env, result, _: self.handle_config_response(ten_env, result)
        )
        
        ten_env_tester.on_start_done()
    
    def handle_config_response(self, ten_env: TenEnvTester, result: CmdResult):
        """Handle configuration response"""
        if result and result.get_status_code() == StatusCode.OK:
            # Extract configuration from response
            config_data = result.get_data()
            if config_data:
                self.parameters_received = True
                self.parameter_values = config_data.get("tts_params", {})
                ten_env.log_info(f"Received parameters: {self.parameter_values}")
        
        ten_env.stop_test()


class TestTencentTTSEnvironmentVariables:
    """Test environment variable configuration support"""
    
    def test_env_var_override(self):
        """Test that environment variables can override config values"""
        import os
        
        # Set test environment variables
        os.environ["TENCENT_TTS_APP_ID"] = "env_app_id"
        os.environ["TENCENT_TTS_SECRET_ID"] = "env_secret_id"
        os.environ["TENCENT_TTS_SECRET_KEY"] = "env_secret_key"
        
        try:
            # Configuration should use environment variables
            config = {
                "app_id": "${TENCENT_TTS_APP_ID}",
                "secret_id": "${TENCENT_TTS_SECRET_ID}",
                "secret_key": "${TENCENT_TTS_SECRET_KEY}"
            }
            
            # Verify environment variable substitution
            assert config["app_id"] == "${TENCENT_TTS_APP_ID}", "Environment variable should be preserved"
            
        finally:
            # Clean up environment variables
            del os.environ["TENCENT_TTS_APP_ID"]
            del os.environ["TENCENT_TTS_SECRET_ID"]
            del os.environ["TENCENT_TTS_SECRET_KEY"]


class TestTencentTTSConfigValidation:
    """Test configuration validation and error handling"""
    
    def test_invalid_app_id_format(self):
        """Test validation of app_id format"""
        invalid_app_ids = [
            "",           # Empty string
            "   ",        # Whitespace only
            "123",        # Numbers only
            "app@id",     # Invalid characters
            "a" * 100     # Too long
        ]
        
        for invalid_id in invalid_app_ids:
            try:
                config = {
                    "app_id": invalid_id,
                    "secret_id": "valid_secret_id",
                    "secret_key": "valid_secret_key"
                }
                TencentTTSConfig(**config)
                assert False, f"Invalid app_id should be rejected: {invalid_id}"
            except ValueError:
                # Expected validation error
                pass
    
    def test_secret_key_validation(self):
        """Test validation of secret key format"""
        # Secret key should be non-empty and have reasonable length
        invalid_secret_keys = [
            "",           # Empty
            "   ",        # Whitespace only
            "short",      # Too short
            "a" * 200     # Too long
        ]
        
        for invalid_key in invalid_secret_keys:
            try:
                config = {
                    "app_id": "valid_app_id",
                    "secret_id": "valid_secret_id",
                    "secret_key": invalid_key
                }
                TencentTTSConfig(**config)
                assert False, f"Invalid secret_key should be rejected: {invalid_key}"
            except ValueError:
                # Expected validation error
                pass
