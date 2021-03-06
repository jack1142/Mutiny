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

import json as json_
from typing import TYPE_CHECKING, Any

import aiohttp
from aiohttp import hdrs

from .authentication_data import AuthenticationData

if TYPE_CHECKING:
    from .state import State

__all__ = ("RESTClient",)


class RESTClient:
    session: aiohttp.ClientSession
    configuration: dict[str, Any]

    def __init__(
        self,
        *,
        authentication_data: AuthenticationData,
        api_url: str,
        state: State,
    ) -> None:
        self.authentication_data = authentication_data
        self.api_url = api_url
        self.headers = self.authentication_data.to_headers()
        self.state = state
        self._prepared = False

    @classmethod
    def from_state(cls, state: State) -> RESTClient:
        client = state.client
        rest = RESTClient(
            authentication_data=client._authentication_data,
            api_url=client.api_url,
            state=state,
        )
        return rest

    async def prepare(self) -> None:
        if self._prepared:
            return
        self.session = aiohttp.ClientSession()
        await self.fetch_configuration()
        self._prepared = True

    async def close(self) -> None:
        if not self._prepared:
            return
        if not self.session.closed:
            await self.session.close()

    def clear(self) -> None:
        if not self._prepared:
            return
        del self.session
        del self.configuration

    @property
    def cdn_url(self) -> str:
        return self.configuration["features"]["autumn"]["url"]

    @property
    def gateway_url(self) -> str:
        return self.configuration["ws"]

    async def request(
        self, method: str, url: str, *, headers: dict[str, Any] = {}, json: Any = None
    ) -> Any:
        async with self.session.request(
            method, url, headers=headers, json=json
        ) as resp:
            text = await resp.text()
            data: Any = ...
            if resp.headers.get(hdrs.CONTENT_TYPE, "") == "application/json":
                data = json_.loads(text)
            if resp.status in (200, 204):
                return data
            else:
                ...

    async def fetch_configuration(self) -> dict[str, Any]:
        self.configuration = await self.request(hdrs.METH_GET, self.api_url)
        return self.configuration
