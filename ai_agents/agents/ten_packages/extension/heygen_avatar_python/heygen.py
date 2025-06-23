import base64
import json
import os
import uuid
import asyncio
import requests
import websockets
import threading

from time import time
from agora_token_builder import RtcTokenBuilder

from ten import AsyncTenEnv


class AgoraHeygenRecorder:
    # Define the base URL as a constant
    HEYGEN_API_BASE_URL = "https://api.heygen.com/v1/"
    SESSION_CACHE_PATH = "/tmp/heygen_session_data.json"
    INTERRUPT_CURL_PATH = "/tmp/heygen_interrupt.txt"
    STOP_CURL_PATH = "/tmp/heygen_stop.txt"
    START_LISTENING_CURL_PATH = "/tmp/heygen_start_listening.txt"
    STOP_LISTENING_CURL_PATH = "/tmp/heygen_stop_listening.txt"
    
    def __init__(self, app_id: str, app_cert: str, heygen_api_key: str, channel_name: str, avatar_uid: int, ten_env: AsyncTenEnv):
        if not app_id or not heygen_api_key:
            raise ValueError("AGORA_APP_ID, AGORA_APP_CERT, and HEYGEN_API_KEY must be provided.")

        self.app_id = app_id
        self.app_cert = app_cert
        self.api_key = heygen_api_key
        self.channel_name = channel_name
        self.uid_avatar = avatar_uid
        self.ten_env = ten_env

        self.token_server = self._generate_token(self.uid_avatar, 1)

        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "x-api-key": self.api_key,
        }
        self.session_headers = None
        self.session_id = None
        self.realtime_endpoint = None
        self.websocket = None
        self.websocket_task = None
        self._should_reconnect = True
        
        # Keep alive task
        self._keep_alive_task: asyncio.Task | None = None
        self._session_running = False

        self._speak_end_timer_task: asyncio.Task | None = None

    def _generate_token(self, uid, role):
        # if the app_cert is not required, return an empty string
        if not self.app_cert:
            return self.app_id

        expire_time = 3600
        privilege_expired_ts = int(time()) + expire_time
        return RtcTokenBuilder.buildTokenWithUid(
            self.app_id,
            self.app_cert,
            self.channel_name,
            uid,
            role,
            privilege_expired_ts,
        )

    def _load_cached_session_data(self):
        if os.path.exists(self.SESSION_CACHE_PATH):
            try:
                with open(self.SESSION_CACHE_PATH, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, KeyError):
                return None
        return None

    def _save_session_data(self, session_id: str, token: str):
        data = {"session_id": session_id, "token": token}
        with open(self.SESSION_CACHE_PATH, "w") as f:
            json.dump(data, f)

    def _clear_session_cache(self):
        if os.path.exists(self.SESSION_CACHE_PATH):
            os.remove(self.SESSION_CACHE_PATH)

    def _write_interrupt_curl(self):
        """Write curl commands for all avatar controls to files"""
        if not self.session_id or not self.session_token:
            return
            
        interrupt_curl = f'''curl -X POST "{self.HEYGEN_API_BASE_URL}streaming.interrupt" \\
  -H "accept: application/json" \\
  -H "content-type: application/json" \\
  -H "authorization: Bearer {self.session_token}" \\
  -d '{{
    "session_id": "{self.session_id}"
  }}\''''
        
        stop_curl = f'''curl -X POST "{self.HEYGEN_API_BASE_URL}streaming.stop" \\
  -H "accept: application/json" \\
  -H "content-type: application/json" \\
  -H "authorization: Bearer {self.session_token}" \\
  -d '{{
    "session_id": "{self.session_id}"
  }}\''''

        start_listening_curl = f'''curl -X POST "{self.HEYGEN_API_BASE_URL}streaming.start_listening" \\
  -H "accept: application/json" \\
  -H "content-type: application/json" \\
  -H "authorization: Bearer {self.session_token}" \\
  -d '{{
    "session_id": "{self.session_id}"
  }}\''''

        stop_listening_curl = f'''curl -X POST "{self.HEYGEN_API_BASE_URL}streaming.stop_listening" \\
  -H "accept: application/json" \\
  -H "content-type: application/json" \\
  -H "authorization: Bearer {self.session_token}" \\
  -d '{{
    "session_id": "{self.session_id}"
  }}\''''
        
        curl_files = [
            (self.INTERRUPT_CURL_PATH, interrupt_curl, "Interrupt"),
            (self.STOP_CURL_PATH, stop_curl, "Stop"),
            (self.START_LISTENING_CURL_PATH, start_listening_curl, "Start listening"),
            (self.STOP_LISTENING_CURL_PATH, stop_listening_curl, "Stop listening")
        ]
        
        try:
            for file_path, curl_command, description in curl_files:
                with open(file_path, "w") as f:
                    f.write(curl_command)
                self.ten_env.log_info(f"{description} curl command written to {file_path}")
        except Exception as e:
            self.ten_env.log_error(f"Failed to write curl commands: {e}")

    async def connect(self):
        await self._create_token()

        # Check and stop old session if needed
        old_session_data = self._load_cached_session_data()
        if old_session_data:
            old_session_id = old_session_data.get("session_id")
            old_token = old_session_data.get("token")
            if old_session_id and old_token:
                try:
                    self.ten_env.log_info(f"Found previous session id: {old_session_id}, attempting to stop it.")
                    await self._stop_session_with_token(old_session_id, old_token)
                    self.ten_env.log_info("Previous session stopped.")
                    self._clear_session_cache()
                except Exception as e:
                    self.ten_env.log_error(f"Failed to stop old session: {e}")

        await self._create_session()
        await self._start_session()
        self._save_session_data(self.session_id, self.session_token)
        
        # Write all curl commands
        self._write_interrupt_curl()
        
        # Start keep alive task
        self._session_running = True
        self._keep_alive_task = asyncio.create_task(self._keep_alive_loop())
        
        self.websocket_task = asyncio.create_task(self._connect_websocket_loop())

    async def disconnect(self):
        self._should_reconnect = False
        self._session_running = False
        
        # Cancel keep alive task
        if self._keep_alive_task:
            self._keep_alive_task.cancel()
            try:
                await self._keep_alive_task
            except asyncio.CancelledError:
                pass
                
        if self.websocket_task:
            self.websocket_task.cancel()
            try:
                await self.websocket_task
            except asyncio.CancelledError:
                pass
        await self._stop_session(self.session_id)

    async def _create_token(self):
        response = requests.post(f"{self.HEYGEN_API_BASE_URL}streaming.create_token", json={}, headers=self.headers)
        self._raise_for_status_verbose(response)
        self.session_token = response.json()["data"]["token"]
        self.session_headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "authorization": f"Bearer {self.session_token}"
        }

    async def _create_session(self):
        payload = {
            "avatar_name": "Wayne_20240711",
            "quality": "high",
            "version": "agora_v1",
            "video_encoding": "H264",
            "source": "app",
            "disable_idle_timeout": False,
            "agora_settings": {
                "app_id": self.app_id,
                "token": self.token_server,
                "channel": self.channel_name,
                "uid": str(self.uid_avatar),
            },
            "namespace": "demo",
        }

        # Log the request details using existing logging mechanism
        self.ten_env.log_info("Creating new session with details:")
        self.ten_env.log_info(f"URL: {self.HEYGEN_API_BASE_URL}streaming.new")
        self.ten_env.log_info(f"Headers: {json.dumps(self.session_headers, indent=2)}")
        self.ten_env.log_info(f"Payload: {json.dumps(payload, indent=2)}")

        response = requests.post(f"{self.HEYGEN_API_BASE_URL}streaming.new", json=payload, headers=self.session_headers)
        self._raise_for_status_verbose(response)
        data = response.json()["data"]
        self.session_id = data["session_id"]
        self.realtime_endpoint = data["realtime_endpoint"]

    def _raise_for_status_verbose(self, response):
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            self.ten_env.log_error(f"HTTP error response: {response.text}")
            raise e

    async def _start_session(self):
        payload = {"session_id": self.session_id}
        self.ten_env.log_info(f"Starting session with payload: {payload}")
        response = requests.post(f"{self.HEYGEN_API_BASE_URL}streaming.start", json=payload, headers=self.session_headers)
        self._raise_for_status_verbose(response)

    async def _stop_session_with_token(self, session_id: str, token: str):
        """Stop session using provided token"""
        try:
            payload = {"session_id": session_id}
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "authorization": f"Bearer {token}"
            }
            self.ten_env.log_info("_stop_session_with_token with details:")
            self.ten_env.log_info(f"URL: {self.HEYGEN_API_BASE_URL}streaming.stop")
            self.ten_env.log_info(f"Headers: {json.dumps(headers, indent=2)}")
            self.ten_env.log_info(f"Payload: {json.dumps(payload, indent=2)}")
            response = requests.post(f"{self.HEYGEN_API_BASE_URL}streaming.stop", json=payload, headers=headers)
            self._raise_for_status_verbose(response)
        except Exception as e:
            print(f"Failed to stop session with token: {e}")

    async def _stop_session(self, session_id: str):
        """Stop session using current session headers"""
        try:
            payload = {"session_id": session_id}
            self.ten_env.log_info("_stop_session with details:")
            self.ten_env.log_info(f"URL: {self.HEYGEN_API_BASE_URL}streaming.stop")
            self.ten_env.log_info(f"Headers: {json.dumps(self.session_headers, indent=2)}")
            self.ten_env.log_info(f"Payload: {json.dumps(payload, indent=2)}")
            response = requests.post(f"{self.HEYGEN_API_BASE_URL}streaming.stop", json=payload, headers=self.session_headers)
            self._raise_for_status_verbose(response)
            self._clear_session_cache()
        except Exception as e:
            print(f"Failed to stop session: {e}")

    # New methods equivalent to the TypeScript ones
    async def start_listening(self):
        """Start listening for audio input"""
        payload = {"session_id": self.session_id}
        self.ten_env.log_info(f"Starting listening with payload: {payload}")
        response = requests.post(f"{self.HEYGEN_API_BASE_URL}streaming.start_listening", json=payload, headers=self.session_headers)
        self._raise_for_status_verbose(response)
        return response.json()

    async def stop_listening(self):
        """Stop listening for audio input"""
        payload = {"session_id": self.session_id}
        self.ten_env.log_info(f"Stopping listening with payload: {payload}")
        response = requests.post(f"{self.HEYGEN_API_BASE_URL}streaming.stop_listening", json=payload, headers=self.session_headers)
        self._raise_for_status_verbose(response)
        return response.json()

    async def interrupt(self):
        """Interrupt the current avatar speech/action"""
        payload = {"session_id": self.session_id}
        self.ten_env.log_info(f"Interrupting session with payload: {payload}")
        response = requests.post(f"{self.HEYGEN_API_BASE_URL}streaming.interrupt", json=payload, headers=self.session_headers)
        self._raise_for_status_verbose(response)
        return response.json()

    async def keep_alive(self):
        """Send keep alive signal to maintain session"""
        payload = {"session_id": self.session_id}
        self.ten_env.log_info(f"Sending keep alive with payload: {payload}")
        response = requests.post(f"{self.HEYGEN_API_BASE_URL}streaming.keep_alive", json=payload, headers=self.session_headers)
        self._raise_for_status_verbose(response)
        self.ten_env.log_info("Keep alive sent successfully")
        return response.json()

    async def _keep_alive_loop(self):
        """Background task to send keep alive every 10 seconds"""
        self.ten_env.log_info("Starting keep alive loop - will send keep alive every 10 seconds")
        while self._session_running:
            try:
                await asyncio.sleep(10)  # Wait 10 seconds
                if self._session_running:  # Check again in case session was stopped during sleep
                    self.ten_env.log_info("Sending keep alive request...")
                    await self.keep_alive()
            except asyncio.CancelledError:
                self.ten_env.log_info("Keep alive loop cancelled")
                break
            except Exception as e:
                self.ten_env.log_error(f"Error in keep alive loop: {e}")
                # Continue the loop even if there's an error

    async def _connect_websocket_loop(self):
        while self._should_reconnect:
            try:
                self.ten_env.log_info("Connecting to WebSocket...")
                async with websockets.connect(self.realtime_endpoint) as ws:
                    self.websocket = ws
                    await asyncio.Future()  # Wait forever unless cancelled
            except Exception as e:
                print(f"WebSocket error: {e}. Reconnecting in 3 seconds...")
                await asyncio.sleep(3)

    def _schedule_speak_end(self):
        """Restart debounce timer every time this is called."""
        # Cancel any existing timer task
        if self._speak_end_timer_task is not None and not self._speak_end_timer_task.done():
            self._speak_end_timer_task.cancel()
        
        # Create a new timer task
        self._speak_end_timer_task = asyncio.create_task(self._debounced_speak_end())

    async def _debounced_speak_end(self):
        """Wait 0.5 seconds, then send speak_end if not cancelled"""
        try:
            await asyncio.sleep(0.5)
            # If we reach here, 500ms passed without being cancelled
            if self.websocket is not None:
                end_evt_id = str(uuid.uuid4())
                await self.websocket.send(json.dumps({
                    "type": "agent.speak_end",
                    "event_id": end_evt_id
                }))
                self.ten_env.log_info("Sent agent.speak_end.")
        except asyncio.CancelledError:
            # Task was cancelled because new audio was sent
            self.ten_env.log_debug("speak_end cancelled due to new audio")
        except Exception as e:
            self.ten_env.log_error(f"Error in speak_end task: {e}")

    async def send(self, audio_base64: str):
        if self.websocket is None:
            raise RuntimeError("WebSocket is not connected.")
        event_id = uuid.uuid4().hex
        await self.websocket.send(json.dumps({
            "type": "agent.speak",
            "audio": audio_base64,
            "event_id": event_id
        }))

        # Schedule agent.speak_end after a short delay
        self._schedule_speak_end()

    def ws_connected(self):
        return self.websocket is not None