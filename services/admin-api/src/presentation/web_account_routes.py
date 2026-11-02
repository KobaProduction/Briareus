"""Retained accounts HTTP adapters with focused dependencies."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from time import monotonic

from application.panel_views import (
    AccountDeleted,
)
from application.provider_verification import ConnectionVerification
from application.services import (
    AccountService,
)
from application.web_accounts import (
    AccountDraft,
    CandidateVerified,
    CreateAccount,
    CreateWebAccount,
    UpdateAccount,
    UpdateWebAccount,
    VerifyCandidate,
    VerifyWebAccountCandidate,
)
from domain.accounts import Provider
from fastapi import APIRouter, HTTPException, Request, status

from common.account_contracts import AccountList, AccountPublic
from presentation.web_accounts import public_account, web_account_errors
from presentation.web_admission import WebAdmission
from presentation.web_models import (
    AccountCandidatePayload,
    AccountPayload,
    AccountUpdatePayload,
)


def _account_draft(payload: AccountPayload) -> AccountDraft:
    return AccountDraft(
        alias=payload.alias,
        provider=payload.provider,
        auth_type=payload.auth_type,
        base_url=payload.base_url,
        external_id=payload.external_id,
        verify_tls=payload.verify_tls,
        ca_cert_pem=payload.ca_cert_pem,
        enabled=payload.enabled,
    )


@dataclass(frozen=True, slots=True)
class WebAccountServices:
    accounts: AccountService
    create: CreateWebAccount
    update: UpdateWebAccount
    candidate: VerifyWebAccountCandidate


@dataclass(eq=False, repr=False)
class WebAccountController:
    admission: WebAdmission
    services: WebAccountServices | None
    candidate_verify_rate_lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)
    candidate_verify_attempts: dict[str, deque[float]] = field(init=False, default_factory=dict)

    def mount(self, router: APIRouter) -> None:
        router.get("/accounts")(self.accounts)
        router.post("/accounts", status_code=201)(self.create_account)
        router.put("/accounts/{provider}/{account_id}")(self.update_account)
        router.delete("/accounts/{provider}/{account_id}")(self.delete_account)
        router.post("/accounts/verify-candidate")(self.verify_account_candidate)
        router.post("/accounts/{provider}/{account_id}/verify")(self.verify_account)

    async def enforce_candidate_verify_rate(self, request: Request) -> None:
        username = self.admission.authenticated_username(request) or "unknown"
        client_host = request.client.host if request.client is not None else "unknown"
        key = f"{username}:{client_host}"
        now = monotonic()
        cutoff = now - 60.0
        async with self.candidate_verify_rate_lock:
            bucket = self.candidate_verify_attempts.setdefault(key, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= 20:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="candidate verification rate limit exceeded",
                    headers={"Retry-After": "60"},
                )
            bucket.append(now)

    async def accounts(self, request: Request, provider: Provider | None = None) -> AccountList:
        self.admission.require_user(request)
        items = await self.admission.available(self.services).accounts.list(provider=provider)
        return AccountList(accounts=items, count=len(items))

    async def create_account(self, payload: AccountPayload, request: Request) -> AccountPublic:
        api = self.admission.mutation(request, self.services)
        command = CreateAccount(_account_draft(payload), payload.credential)
        with web_account_errors():
            saved = await api.create.execute(command)
        return public_account(saved)

    async def update_account(
        self, provider: Provider, account_id: str, payload: AccountUpdatePayload, request: Request
    ) -> AccountPublic:
        api = self.admission.mutation(request, self.services)
        command = UpdateAccount(
            provider,
            account_id,
            _account_draft(payload),
            payload.credential,
            payload.expected_updated_at,
        )
        with web_account_errors():
            saved = await api.update.execute(command)
        return public_account(saved)

    async def delete_account(
        self, provider: Provider, account_id: str, request: Request
    ) -> AccountDeleted:
        api = self.admission.mutation(request, self.services)
        try:
            await api.accounts.delete(account_id, provider=provider)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return AccountDeleted(deleted=True, id=account_id, provider=provider.value)

    async def verify_account_candidate(
        self, payload: AccountCandidatePayload, request: Request
    ) -> CandidateVerified:
        api = self.admission.mutation(request, self.services)
        await self.enforce_candidate_verify_rate(request)
        command = VerifyCandidate(
            _account_draft(payload), payload.credential, payload.account_id, payload.draft_revision
        )
        with web_account_errors():
            return await api.candidate.execute(command)

    async def verify_account(
        self, provider: Provider, account_id: str, request: Request
    ) -> ConnectionVerification:
        api = self.admission.mutation(request, self.services)
        try:
            return await api.accounts.verify(account_id, provider=provider)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
