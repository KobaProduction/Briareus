from __future__ import annotations

import json
from collections.abc import Sequence

import mcp_types as mt
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import InputRequiredToolResult, Tool, ToolResult
from mcp.types import TextContent

from bridge.application.access_session import (
    AccessValidationUnavailable,
    AdmitSessionTool,
    SessionToolAttempt,
)
from bridge.domain.access_session import denial_message, is_base_read_only
from bridge.infrastructure.access_session import HttpSessionValidation
from bridge.presentation.access_session import AccessSessionError, SessionMetadata
from common.access_contracts import OAuthContext, SessionSnapshot
from common.mcp_surfaces import surface_id

from .authorization_access_client import AuthorizationAccessClient

_ACCESS_TOOL_PREFIX = "access_session_"


def oauth_context() -> OAuthContext:
    token = get_access_token()
    if token is None:
        raise RuntimeError("OAuth access token is unavailable")
    claims = token.claims or {}
    user_id = token.subject or ""
    oauth_session_id = str(claims.get("session_id") or "")
    if not user_id or not token.client_id or not oauth_session_id:
        raise RuntimeError("OAuth token is missing local identity/session claims")
    return OAuthContext(
        user_id=user_id,
        client_id=token.client_id,
        oauth_session_id=oauth_session_id,
    )


def _with_session_parameter(tool: Tool) -> Tool:
    if tool.name.startswith(_ACCESS_TOOL_PREFIX):
        return tool
    parameters = dict(tool.parameters)
    properties = dict(parameters.get("properties") or {})
    if "session_id" not in properties:
        properties["session_id"] = {
            "type": "string",
            "description": (
                "Agent access session UID. Required when session control is enabled "
                "for this MCP surface."
            ),
        }
    parameters["properties"] = properties
    return tool.model_copy(update={"parameters": parameters})


def _session_meta(session: SessionSnapshot) -> SessionMetadata:
    return SessionMetadata(
        session_id=session.uid,
        status=session.status,
        access_level=session.access_level,
        expires_at=session.expires_at,
        account_scope=session.account_scope,
    )


class AccessSessionMiddleware(Middleware):
    def __init__(
        self,
        *,
        surface: str,
        client: AuthorizationAccessClient,
    ) -> None:
        self.surface = surface
        self.surface_id = int(surface_id(surface))
        self.client = client
        self._admission = AdmitSessionTool(HttpSessionValidation(client))

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        return [_with_session_parameter(tool) for tool in tools]

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name = context.message.name
        if tool_name.startswith(_ACCESS_TOOL_PREFIX):
            return await call_next(context)

        arguments = dict(context.message.arguments or {})
        raw_session_id = arguments.pop("session_id", "")
        session_uid = raw_session_id if isinstance(raw_session_id, str) else ""

        tool = await self._resolve_tool(context, tool_name)
        account_id_raw = arguments.get("account_id", "")
        account_id = account_id_raw if isinstance(account_id_raw, str) else ""

        try:
            decision = await self._admission.execute(
                oauth_context(),
                SessionToolAttempt(
                    surface=self.surface,
                    surface_id=self.surface_id,
                    tool_name=tool_name,
                    session_uid=session_uid,
                    account_id=account_id,
                    read_only_hint=bool(
                        tool is not None
                        and tool.annotations is not None
                        and tool.annotations.read_only_hint is True
                    ),
                ),
            )
        except AccessValidationUnavailable as exc:
            return self._error(
                "auth_access_unavailable",
                "Access validation is temporarily unavailable.",
                detail=exc.error_type,
            )
        except (ValueError, RuntimeError) as exc:
            return self._error(
                "auth_access_unavailable",
                "Access validation is temporarily unavailable.",
                detail=type(exc).__name__,
            )

        if not decision.allowed:
            return self._error(
                decision.code,
                self._message_for_code(decision.code),
                session=decision.session,
                retry_after_seconds=decision.retry_after_seconds,
            )

        forwarded = context.message.model_copy(update={"arguments": arguments})
        result = await call_next(context.copy(message=forwarded))
        return self._with_session_result(result, decision.session)

    async def _resolve_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        tool_name: str,
    ) -> Tool | None:
        fastmcp_context = context.fastmcp_context
        if fastmcp_context is None:
            return None
        return await fastmcp_context.fastmcp.get_tool(tool_name)

    def _is_base_read_only(self, tool_name: str, tool: Tool | None) -> bool:
        return is_base_read_only(
            self.surface,
            tool_name,
            read_only_hint=bool(
                tool is not None
                and tool.annotations is not None
                and tool.annotations.read_only_hint is True
            ),
        )

    @staticmethod
    def _with_session_result(result: ToolResult, session: SessionSnapshot | None) -> ToolResult:
        if session is None or isinstance(result, InputRequiredToolResult):
            return result
        session_context = _session_meta(session).model_dump()
        meta = dict(result.meta or {})
        meta["access_session"] = session_context
        content = list(result.content)
        content.append(
            TextContent(
                type="text",
                text=json.dumps(
                    {"access_session": session_context},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        )
        # Rebuild instead of model_copy: proxied ToolResult may retain a private
        # raw MCP result whose wire serialization would otherwise ignore updates.
        return ToolResult(
            content=content,
            structured_content=result.structured_content,
            meta=meta,
            is_error=result.is_error,
        )

    @staticmethod
    def _message_for_code(code: str) -> str:
        return denial_message(code)

    @staticmethod
    def _error(
        code: str,
        message: str,
        *,
        session: SessionSnapshot | None = None,
        retry_after_seconds: int = 0,
        detail: str = "",
    ) -> ToolResult:
        metadata = _session_meta(session) if session is not None else None
        view = AccessSessionError(
            error=code,
            message=message,
            retry_after_seconds=retry_after_seconds or None,
            detail=detail or None,
            access_session=metadata,
        )
        session_context = metadata.model_dump() if metadata is not None else {}
        meta = {"access_session": session_context}
        content = [TextContent(type="text", text=message)]
        if session_context:
            content.append(
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"access_session": session_context},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
            )
        return ToolResult(
            content=content,
            structured_content=view.model_dump(mode="json", exclude_none=True),
            meta=meta,
            is_error=True,
        )
