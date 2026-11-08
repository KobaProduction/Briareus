from __future__ import annotations

import asyncio
from datetime import UTC

from briareus_account_contracts import AccountList, AccountPublic
from fastapi import APIRouter, HTTPException, Request, status

from control_panel_api.domain.accounts import Account, AccountConflictError, Provider
from control_panel_api.domain.verification import ConnectionVerification

from .context import WebApiContext
from .contracts import (
    AccountCandidatePayload,
    AccountPayload,
    AccountUpdatePayload,
    _account_from_payload,
)
from .response_contracts import AccountDeletion, CandidateVerification


class AccountsRoutes:
    def __init__(self, context: WebApiContext) -> None:
        self.context = context

    def register(self, router: APIRouter) -> None:
        router.add_api_route("/accounts", self.accounts, methods=["GET"])
        router.add_api_route("/accounts", self.create_account, methods=["POST"], status_code=201)
        router.add_api_route(
            "/accounts/{provider}/{account_id}", self.update_account, methods=["PUT"]
        )
        router.add_api_route(
            "/accounts/{provider}/{account_id}", self.delete_account, methods=["DELETE"]
        )
        router.add_api_route(
            "/accounts/verify-candidate", self.verify_account_candidate, methods=["POST"]
        )
        router.add_api_route(
            "/accounts/{provider}/{account_id}/verify", self.verify_account, methods=["POST"]
        )

    async def accounts(self, request: Request, provider: Provider | None = None) -> AccountList:
        self.context.require_user(request)
        items = await asyncio.to_thread(self.context.available().accounts.list, provider=provider)
        return AccountList(accounts=items, count=len(items))

    async def create_account(self, payload: AccountPayload, request: Request) -> AccountPublic:
        api = self.context.mutation(request)
        try:
            account = _account_from_payload(payload)
            saved = await asyncio.to_thread(
                api.accounts.create, account, credential=payload.credential
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return saved.public()

    async def update_account(
        self, provider: Provider, account_id: str, payload: AccountUpdatePayload, request: Request
    ) -> AccountPublic:
        api = self.context.mutation(request)
        if payload.provider is not provider:
            raise HTTPException(status_code=400, detail="provider cannot be changed")
        try:
            existing = await asyncio.to_thread(
                api.accounts.get, account_id, provider=provider, enabled_only=False
            )
            if payload.expected_updated_at is not None:
                expected = payload.expected_updated_at
                if expected.tzinfo is None:
                    expected = expected.replace(tzinfo=UTC)
                else:
                    expected = expected.astimezone(UTC)
                persisted = existing.updated_at
                if persisted.tzinfo is None:
                    persisted = persisted.replace(tzinfo=UTC)
                else:
                    persisted = persisted.astimezone(UTC)
                if expected != persisted:
                    raise AccountConflictError("account changed since it was loaded")
            saved = await asyncio.to_thread(
                api.accounts.update,
                _account_from_payload(payload, existing=existing),
                credential=payload.credential,
                expected_updated_at=existing.updated_at if payload.expected_updated_at else None,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AccountConflictError as exc:
            try:
                current = await asyncio.to_thread(
                    api.accounts.get, account_id, provider=provider, enabled_only=False
                )
                current_updated_at: str | None = current.public().updated_at
            except KeyError:
                current_updated_at = None
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "account_conflict",
                    "message": "account changed since it was loaded; reload before saving",
                    "current_updated_at": current_updated_at,
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return saved.public()

    async def delete_account(
        self, provider: Provider, account_id: str, request: Request
    ) -> AccountDeletion:
        api = self.context.mutation(request)
        try:
            await asyncio.to_thread(api.accounts.delete, account_id, provider=provider)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return AccountDeletion(id=account_id, provider=provider)

    async def verify_account_candidate(
        self, payload: AccountCandidatePayload, request: Request
    ) -> CandidateVerification:
        api = self.context.mutation(request)
        await self.context.enforce_candidate_verify_rate(request)
        existing: Account | None = None
        try:
            if payload.account_id:
                existing = await asyncio.to_thread(
                    api.accounts.get,
                    payload.account_id,
                    provider=payload.provider,
                    enabled_only=False,
                )
            account = _account_from_payload(payload, existing=existing)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="account not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not payload.credential.strip() and existing is None:
            raise HTTPException(status_code=400, detail="credential is required for a new account")
        try:
            async with self.context.candidate_verify_slots:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        api.accounts.verify_candidate,
                        account,
                        credential=payload.credential,
                        credential_account_id=existing.id if existing is not None else "",
                    ),
                    timeout=20.0,
                )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="candidate verification timed out",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="candidate verification failed"
            ) from exc
        if result.ok is not True:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="candidate verification failed"
            )
        return CandidateVerification(
            provider=payload.provider,
            draft_revision=payload.draft_revision,
        )

    async def verify_account(
        self, provider: Provider, account_id: str, request: Request
    ) -> ConnectionVerification:
        api = self.context.mutation(request)
        try:
            return await asyncio.to_thread(api.accounts.verify, account_id, provider=provider)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
