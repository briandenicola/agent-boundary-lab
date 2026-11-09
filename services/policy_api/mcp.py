"""MCP transport for the same protected synthetic servicing lookup."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request

from containment_demo.delegated_auth import DelegatedUser


def create_mcp_app() -> tuple[MCPServer[Any], Starlette]:
    server: MCPServer[Any] = MCPServer("servicing-policy", log_level="WARNING")

    @server.tool()
    async def get_servicing_policy(
        demo_run_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
        ctx: Context[Any, Any],
    ) -> dict[str, Any]:
        """Retrieve the synthetic servicing policy as the authenticated user."""
        from services.policy_api.main import serve_policy

        request = ctx.request_context.request
        if not isinstance(request, Request) or not isinstance(
            getattr(request.state, "delegated_user", None), DelegatedUser
        ):
            raise PermissionError("delegated authorization required")
        return serve_policy(request, demo_run_id, transport="mcp")

    return server, server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        max_request_body_size=16_384,
        host="0.0.0.0",  # noqa: S104 -- ACA ingress terminates HTTPS; middleware authenticates MCP.
    )
