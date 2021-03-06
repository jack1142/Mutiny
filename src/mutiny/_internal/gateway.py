# Copyright 2021 Jakub Kuczys (https://github.com/jack1142)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Literal, Optional

import aiohttp
import yarl

try:
    import msgpack
except ModuleNotFoundError:
    HAS_MSGPACK = False
else:
    HAS_MSGPACK = True

from ..events import Event
from .authentication_data import AuthenticationData
from .backoff import ExponentialBackoff
from .errors import AuthenticationError
from .event_handler import EventHandler

if TYPE_CHECKING:
    from .state import State

__all__ = ("GatewayMessageFormat", "GatewayClient")

_log = logging.getLogger(__name__)

GatewayMessageFormat = Literal["json", "msgpack"]


class GatewayClient:
    url: str
    ws: aiohttp.ClientWebSocketResponse
    gateway_format: GatewayMessageFormat

    def __init__(
        self,
        *,
        authentication_data: AuthenticationData,
        event_handler: EventHandler,
        state: State,
        gateway_format: GatewayMessageFormat,
    ) -> None:
        self.authentication_data = authentication_data
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.event_handler = event_handler
        self.state = state
        self.set_gateway_format(gateway_format)
        self._prepared = False
        self._closed = False
        self.authenticated = False

    def set_gateway_format(self, gateway_format: GatewayMessageFormat):
        self.gateway_format = gateway_format
        if gateway_format == "json":
            self.parse_message = self._parse_json_message
            self.send_message = self._send_json_message
        else:
            self.parse_message = self._parse_msgpack_message
            self.send_message = self._send_msgpack_message

    @classmethod
    def from_state(cls, state: State) -> GatewayClient:
        client = state.client
        gateway = GatewayClient(
            authentication_data=client._authentication_data,
            event_handler=client._event_handler,
            state=state,
            gateway_format=client._gateway_format,
        )
        return gateway

    async def prepare(self) -> None:
        if self._prepared:
            return
        rest = self.state.rest
        await rest.prepare()
        self.url = rest.gateway_url
        self.session = rest.session

    async def close(self) -> None:
        if self._closed:
            return
        if not self.ws.closed:
            await self.ws.close()
        self._closed = True
        self.authenticated = False

    def clear(self):
        if not self._prepared:
            return
        del self.url
        del self.session

    async def start(self) -> None:
        backoff = ExponentialBackoff(max_attempts=None)
        while not self._closed:
            if self.authenticated:
                # Let's go with an assumption that if we managed to get authenticated
                # successfully before the connection got closed, it's as if we were
                # starting a new retrying loop.
                backoff.reset()
            await backoff.delay(_log, "Attempting a reconnect in %.2fs")

            try:
                await self.connect()
            except (aiohttp.ClientError, asyncio.TimeoutError):
                _log.info("Failed to connect to the gateway, attempting a reconnect...")
                continue

            if self.ws.close_code is None:
                _log.info("Websocket connection closed by the client.")
                return
            _log.info(
                "Websocket connection closed with code %s, attempting a reconnect...",
                self.ws.close_code,
            )

    async def connect(self) -> None:
        self.authenticated = False
        await self.prepare()
        url = yarl.URL(self.url).update_query(format=self.gateway_format)
        self.ws = await self.session.ws_connect(
            url, timeout=30.0, max_msg_size=0, heartbeat=10.0
        )
        await self.authenticate()

        await self.poll_loop()

    async def poll_loop(self) -> None:
        async for msg in self.ws:
            if msg.type is aiohttp.WSMsgType.ERROR:
                raise msg.data

            try:
                event = Event._from_dict(self.state, self.parse_message(msg))
                await event._gateway_handle()
            except AuthenticationError:
                raise
            except Exception as exc:
                _log.critical(
                    "Couldn't process an event, the gateway might now be in bad state."
                    "\nPlease search for this issue at"
                    " https://github.com/jack1142/Mutiny/issues and report it"
                    " if someone else has not done it already.\n"
                    "Be sure to include the payload data and the exception traceback"
                    " logged below:\n%s",
                    msg.data,
                    exc_info=exc,
                )
                continue
            self.event_handler.dispatch(event)

    async def authenticate(self) -> None:
        payload = {
            "type": "Authenticate",
            **self.authentication_data.to_dict(),
        }
        await self.send_message(payload)

    async def begin_typing(self, channel_id: str) -> None:
        payload = {
            "type": "BeginTyping",
            "channel": channel_id,
        }
        await self.send_message(payload)

    async def end_typing(self, channel_id: str) -> None:
        payload = {
            "type": "EndTyping",
            "channel": channel_id,
        }
        await self.send_message(payload)

    async def ping(self, time: int = 0) -> None:
        payload: dict[str, Any] = {"type": "Ping"}
        if time:
            payload["time"] = time
        await self.send_message(payload)

    @staticmethod
    def _parse_msgpack_message(msg: aiohttp.WSMessage) -> dict[str, Any]:
        if msg.type is not aiohttp.WSMsgType.BINARY:
            raise RuntimeError(
                f"got {msg}, but can't handle its type"
                " with currently selected gateway format"
            )
        return msgpack.unpackb(msg.data)

    @staticmethod
    def _parse_json_message(msg: aiohttp.WSMessage) -> dict[str, Any]:
        if msg.type is not aiohttp.WSMsgType.TEXT:
            raise RuntimeError(
                f"got {msg}, but can't handle its type"
                " with currently selected gateway format"
            )
        return json.loads(msg.data)

    async def _send_msgpack_message(self, data: dict[str, Any]) -> None:
        await self.ws.send_bytes(msgpack.packb(data))

    async def _send_json_message(self, data: dict[str, Any]) -> None:
        await self.ws.send_str(json.dumps(data))
