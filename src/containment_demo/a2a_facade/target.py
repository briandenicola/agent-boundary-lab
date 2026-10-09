"""The Foundry adapter: the ONLY module in this package that knows about Foundry.

Reuses ``containment_demo.invoke``'s proven call path: ``build_agent_client`` (Entra token
for https://ai.azure.com/.default via DefaultAzureCredential, agent addressed by name on
the project endpoint) and ``responses.create(..., store=False)``. Nothing here is a second
way to reach the platform; it is the same one with the caller's text instead of the demo
prompt.
"""

from __future__ import annotations

import asyncio
from typing import Any

from containment_demo import invoke
from containment_demo.a2a_facade.core import TargetError, TargetReply


def _response_id(response: Any) -> str | None:
    raw = response.get("id") if isinstance(response, dict) else getattr(response, "id", None)
    return str(raw) if raw else None


class ResponsesTarget:
    def __init__(
        self,
        *,
        endpoint: str,
        agent_name: str,
        timeout_seconds: float,
        client: Any | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._agent_name = agent_name
        self._timeout = timeout_seconds
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = invoke.build_agent_client(
                self._endpoint, self._agent_name, self._timeout
            )
        return self._client

    def _call(self, text: str) -> TargetReply:
        try:
            response = self._get_client().responses.create(
                model="",
                input=text,
                store=invoke.STORE_RESPONSE,
                timeout=self._timeout,
            )
        except Exception as exc:  # classified, never masked as success
            raise TargetError(
                str(invoke.classify_invocation_exception(exc)), invoke.http_status_of(exc)
            ) from None
        outcomes = invoke.outcomes_from_response(response)
        run_ids = tuple(dict.fromkeys(o.tool_run_id for o in outcomes.values() if o.tool_run_id))
        return TargetReply(
            text="\n".join(invoke.response_texts(response)),
            response_id=_response_id(response),
            tool_run_ids=run_ids,
        )

    async def send(self, text: str) -> TargetReply:
        return await asyncio.to_thread(self._call, text)
