import base64
import json
import uuid
import asyncio
import requests
import websockets

from time import time
from agora_token_builder import RtcTokenBuilder

from ten import AsyncTenEnv


class AgoraHeygenRecorder:
    def __init__(self, app_id: str, app_cert: str, heygen_api_key: str, channel_name: str, avatar_uid: int, ten_env: AsyncTenEnv):
        if not app_id or not app_cert or not heygen_api_key:
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

    def _generate_token(self, uid, role):
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

    async def connect(self):
        await self._create_token()
        await self._create_session()
        await self._start_session()
        self.websocket_task = asyncio.create_task(self._connect_websocket_loop())

    async def disconnect(self):
        self._should_reconnect = False
        if self.websocket_task:
            self.websocket_task.cancel()
            try:
                await self.websocket_task
            except asyncio.CancelledError:
                pass
        await self._stop_session()

    async def _create_token(self):
        response = requests.post("https://api.heygen.com/v1/streaming.create_token", json={}, headers=self.headers)
        response.raise_for_status()
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
        response = requests.post("https://api.heygen.com/v1/streaming.new", json=payload, headers=self.session_headers)
        response.raise_for_status()
        data = response.json()["data"]
        self.session_id = data["session_id"]
        self.realtime_endpoint = data["realtime_endpoint"]

    async def _start_session(self):
        payload = {"session_id": self.session_id}
        response = requests.post("https://api.heygen.com/v1/streaming.start", json=payload, headers=self.session_headers)
        response.raise_for_status()

    async def _stop_session(self):
        try:
            payload = {"session_id": self.session_id}
            requests.post("https://api.heygen.com/v1/streaming.stop", json=payload, headers=self.session_headers)
        except Exception as e:
            print(f"Failed to stop session: {e}")

    async def _connect_websocket_loop(self):
        while self._should_reconnect:
            try:
                async with websockets.connect(self.realtime_endpoint) as ws:
                    self.websocket = ws
                    await asyncio.Future()  # Wait forever unless cancelled
            except Exception as e:
                print(f"WebSocket error: {e}. Reconnecting in 3 seconds...")
                await asyncio.sleep(3)

    async def send(self, audio_base64: str):
        if self.websocket is None:
            raise RuntimeError("WebSocket is not connected.")
        event_id = uuid.uuid4().hex
        await self.websocket.send(json.dumps({"type": "agent.audio_buffer_append", "audio": audio_base64, "event_id": event_id}))
        await self.websocket.send(json.dumps({"type": "agent.audio_buffer_commit", "audio": "", "event_id": event_id}))
