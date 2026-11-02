"""Retained oauth HTTP adapters with focused dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from application.internal_views import OAuthSessionList, OAuthSessionView
from application.services import (
    OAuthSessionService,
)
from fastapi import APIRouter, Query, Request

from presentation.web_admission import WebAdmission


@dataclass(eq=False, repr=False)
class WebOAuthController:
    admission: WebAdmission
    sessions: OAuthSessionService | None

    def mount(self, router: APIRouter) -> None:
        router.get("/oauth-sessions")(self.oauth_sessions)

    async def oauth_sessions(
        self, request: Request, limit: int = Query(200, ge=1, le=1000)
    ) -> OAuthSessionList:
        self.admission.require_user(request)
        items = await self.admission.available(self.sessions).recent(limit=limit)
        return OAuthSessionList(
            sessions=[OAuthSessionView.from_record(item) for item in items], count=len(items)
        )
