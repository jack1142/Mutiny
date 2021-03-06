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

from typing import Any, Optional

__all__ = ("AuthenticationData",)


class AuthenticationData:
    __slots__ = ("token", "session_token")

    def __init__(
        self,
        *,
        token: Optional[str] = None,
        session_token: Optional[str] = None,
    ) -> None:
        if token is not None:
            if session_token is not None:
                raise ValueError(
                    "You can either pass `token` (for bot session),"
                    " or `session_token` (for user session),"
                    " you cannot pass both of them!"
                )
        elif session_token is None:
            raise ValueError(
                "You have to either pass `token` (for bot session),"
                " or `session_token` (for user session),"
                " but you did not pass either!"
            )

        self.token = token
        self.session_token = session_token

    def to_dict(self) -> dict[str, Any]:
        return {"token": self.token or self.session_token}

    def to_headers(self) -> dict[str, Any]:
        if self.token is not None:
            return {"x-bot-token": self.token or self.session_token}
        return {"x-session-token": self.session_token}
