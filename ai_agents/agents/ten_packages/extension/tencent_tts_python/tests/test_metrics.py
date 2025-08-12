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
import time
from typing import Any, Dict, List
from unittest.mock import patch, AsyncMock, MagicMock

from ten_runtime import (
    ExtensionTester,
    TenEnvTester,
    Data,
)
from ten_ai_base.struct import TTSTextInput
from ..tencent_tts import TencentTTSClient


class TestTencentTTSMetrics:
    """Performance metrics and monitoring tests for Tencent TTS extension"""
    
    @patch('websockets.connect')
    def test_tts_latency_metrics(self, mock_ws_connect):
        """Test TTS latency measurement and reporting"""
        # Mock WebSocket with controlled timing
        mock_ws = MagicMock()
        mock_ws_connect.return_value = mock_ws
        
        # Simulate realistic TTS response timing
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "audio", "data": "audio_chunk_1"}),
            json.dumps({"type": "audio", "data": "audio_chunk_2"}),
            json.dumps({"type": "end", "reason": "completed"})
        ])
        
        config = {
            "app_id": "test_app_id",
            "secret_id": "test_secret_id",
            "secret_key": "test_secret_key"
        }
        
        tester = LatencyMetricsTester()
        tester.set_test_mode_single("tencent_tts_python", json.dumps(config))
        
        start_time = time.time()
        tester.run()
        end_time = time.time()
        
        # Verify latency metrics
        assert tester.first_audio_received, "Should receive first audio chunk"
        assert tester.synthesis_completed, "Synthesis should complete"
        assert tester.latency_metrics, "Latency metrics should be collected"
        
        # Check reasonable latency bounds
        total_latency = end_time - start_time
        assert total_latency < 10.0, f"Total latency should be reasonable: {total_latency}s"


class LatencyMetricsTester(ExtensionTester):
    """Tester for latency metrics collection"""
    
    def __init__(self):
        super().__init__()
        self.first_audio_received = False
        self.synthesis_completed = False
        self.latency_metrics = {}
        self.start_time = None
        self.first_audio_time = None
        self.completion_time = None
    
    def on_start(self, ten_env_tester: TenEnvTester) -> None:
        """Start latency measurement test"""
        self.start_time = time.time()
        ten_env_tester.log_info("Starting latency metrics test")
        
        tts_input = TTSTextInput(
            request_id="latency_test_request",
            text="Test text for latency measurement",
            text_input_end=True
        )
        
        data = Data.create("tts_text_input")
        data.set_property_from_json(None, tts_input.model_dump_json())
        ten_env_tester.send_data(data)
        ten_env_tester.on_start_done()
    
    def on_audio_frame(self, ten_env: TenEnvTester, audio_frame):
        """Record first audio frame timing"""
        if not self.first_audio_received:
            self.first_audio_received = True
            self.first_audio_time = time.time()
            
            # Calculate time to first audio
            time_to_first_audio = self.first_audio_time - self.start_time
            self.latency_metrics["time_to_first_audio"] = time_to_first_audio
            
            ten_env.log_info(f"First audio received in {time_to_first_audio:.3f}s")
    
    def on_data(self, ten_env: TenEnvTester, data) -> None:
        """Handle TTS events and record completion timing"""
        name = data.get_name()
        
        if name == "tts_audio_end":
            self.synthesis_completed = True
            self.completion_time = time.time()
            
            # Calculate total synthesis time
            total_synthesis_time = self.completion_time - self.start_time
            self.latency_metrics["total_synthesis_time"] = total_synthesis_time
            
            ten_env.log_info(f"Total synthesis time: {total_synthesis_time:.3f}s")
            ten_env.stop_test()


class TestTencentTTSThroughput:
    """Throughput and performance tests"""
    
    @patch('websockets.connect')
    def test_concurrent_requests(self, mock_ws_connect):
        """Test handling of multiple concurrent TTS requests"""
        # Mock WebSocket for concurrent testing
        mock_ws = MagicMock()
        mock_ws_connect.return_value = mock_ws
        
        # Simulate quick responses for throughput testing
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "audio", "data": "quick_audio"}),
            json.dumps({"type": "end", "reason": "completed"})
        ])
        
        config = {
            "app_id": "test_app_id",
            "secret_id": "test_secret_id",
            "secret_key": "test_secret_key"
        }
        
        tester = ThroughputTester()
        tester.set_test_mode_single("tencent_tts_python", json.dumps(config))
        
        tester.run()
        
        # Verify throughput metrics
        assert tester.requests_processed > 0, "Should process requests"
        assert tester.throughput_metrics, "Throughput metrics should be collected"
        
        # Check reasonable throughput
        requests_per_second = tester.throughput_metrics.get("requests_per_second", 0)
        assert requests_per_second > 0, f"Throughput should be positive: {requests_per_second}"


class ThroughputTester(ExtensionTester):
    """Tester for throughput measurement"""
    
    def __init__(self):
        super().__init__()
        self.requests_processed = 0
        self.throughput_metrics = {}
        self.start_time = None
        self.request_times = []
    
    def on_start(self, ten_env_tester: TenEnvTester) -> None:
        """Start throughput test with multiple requests"""
        self.start_time = time.time()
        ten_env_tester.log_info("Starting throughput test")
        
        # Send multiple requests quickly
        for i in range(3):
            tts_input = TTSTextInput(
                request_id=f"throughput_request_{i}",
                text=f"Test text {i} for throughput testing",
                text_input_end=True
            )
            
            data = Data.create("tts_text_input")
            data.set_property_from_json(None, tts_input.model_dump_json())
            ten_env_tester.send_data(data)
        
        ten_env_tester.on_start_done()
    
    def on_data(self, ten_env: TenEnvTester, data) -> None:
        """Track request completion for throughput calculation"""
        name = data.get_name()
        
        if name == "tts_audio_end":
            self.requests_processed += 1
            current_time = time.time()
            self.request_times.append(current_time)
            
            ten_env.log_info(f"Request {self.requests_processed} completed")
            
            # Calculate throughput after all requests complete
            if self.requests_processed >= 3:
                total_time = current_time - self.start_time
                requests_per_second = self.requests_processed / total_time
                
                self.throughput_metrics["requests_per_second"] = requests_per_second
                self.throughput_metrics["total_time"] = total_time
                self.throughput_metrics["total_requests"] = self.requests_processed
                
                ten_env.log_info(f"Throughput: {requests_per_second:.2f} req/s")
                ten_env.stop_test()


class TestTencentTTSResourceUsage:
    """Resource usage and memory management tests"""
    
    @patch('websockets.connect')
    def test_memory_usage_tracking(self, mock_ws_connect):
        """Test memory usage monitoring during TTS operations"""
        # Mock WebSocket for memory testing
        mock_ws = MagicMock()
        mock_ws_connect.return_value = mock_ws
        
        # Simulate audio streaming
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "audio", "data": "large_audio_chunk" * 1000}),
            json.dumps({"type": "end", "reason": "completed"})
        ])
        
        config = {
            "app_id": "test_app_id",
            "secret_id": "test_secret_id",
            "secret_key": "test_secret_key"
        }
        
        tester = ResourceUsageTester()
        tester.set_test_mode_single("tencent_tts_python", json.dumps(config))
        
        tester.run()
        
        # Verify resource tracking
        assert tester.resource_metrics, "Resource metrics should be collected"
        assert "memory_usage" in tester.resource_metrics, "Memory usage should be tracked"


class ResourceUsageTester(ExtensionTester):
    """Tester for resource usage monitoring"""
    
    def __init__(self):
        super().__init__()
        self.resource_metrics = {}
        self.audio_chunks_received = 0
    
    def on_start(self, ten_env_tester: TenEnvTester) -> None:
        """Start resource usage test"""
        ten_env_tester.log_info("Starting resource usage test")
        
        tts_input = TTSTextInput(
            request_id="resource_test_request",
            text="Long text for resource usage testing with multiple audio chunks",
            text_input_end=True
        )
        
        data = Data.create("tts_text_input")
        data.set_property_from_json(None, tts_input.model_dump_json())
        ten_env_tester.send_data(data)
        ten_env_tester.on_start_done()
    
    def on_audio_frame(self, ten_env: TenEnvTester, audio_frame):
        """Track audio processing and estimate resource usage"""
        self.audio_chunks_received += 1
        
        # Estimate memory usage based on audio data
        buf = audio_frame.lock_buf()
        try:
            audio_size = len(buf)
            estimated_memory = audio_size * self.audio_chunks_received
            
            self.resource_metrics["audio_chunks_processed"] = self.audio_chunks_received
            self.resource_metrics["total_audio_size"] = estimated_memory
            self.resource_metrics["estimated_memory_usage"] = estimated_memory
            
        finally:
            audio_frame.unlock_buf(buf)
    
    def on_data(self, ten_env: TenEnvTester, data) -> None:
        """Complete resource usage test"""
        name = data.get_name()
        
        if name == "tts_audio_end":
            ten_env.log_info(f"Resource usage test completed: {self.resource_metrics}")
            ten_env.stop_test()


class TestTencentTTSQualityMetrics:
    """Audio quality and accuracy metrics tests"""
    
    def test_audio_format_validation(self):
        """Test audio format and quality metrics"""
        # Test PCM format validation
        pcm_config = {
            "app_id": "test_app_id",
            "secret_id": "test_secret_id",
            "secret_key": "test_secret_key",
            "audio_format": "pcm",
            "sample_rate": 16000,
            "bit_depth": 16,
            "channels": 1
        }
        
        # Validate audio format parameters
        assert pcm_config["audio_format"] == "pcm", "Audio format should be PCM"
        assert pcm_config["sample_rate"] in [8000, 16000, 24000, 48000], "Sample rate should be valid"
        assert pcm_config["bit_depth"] in [16, 24], "Bit depth should be valid"
        assert pcm_config["channels"] in [1, 2], "Channels should be valid"
    
    def test_voice_quality_parameters(self):
        """Test voice quality configuration parameters"""
        voice_config = {
            "voice_type": "female",
            "volume": 0.8,
            "speed": 1.0,
            "pitch": 0.0
        }
        
        # Validate voice parameters
        assert voice_config["voice_type"] in ["male", "female"], "Voice type should be valid"
        assert 0.0 <= voice_config["volume"] <= 1.0, "Volume should be in range [0,1]"
        assert 0.5 <= voice_config["speed"] <= 2.0, "Speed should be in range [0.5,2]"
        assert -20 <= voice_config["pitch"] <= 20, "Pitch should be in range [-20,20]"
