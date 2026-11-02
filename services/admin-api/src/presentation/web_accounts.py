"""HTTP account responses and translation of account workflow failures."""

from collections.abc import Iterator
from contextlib import contextmanager

from application.account_views import public_account as public_account
from domain.web_accounts import (
    AccountInputRejected,
    AccountMissing,
    AccountUpdateConflict,
    CandidateVerificationFailed,
    CandidateVerificationTimedOut,
)
from fastapi import HTTPException


@contextmanager
def web_account_errors() -> Iterator[None]:
    try:
        yield
    except AccountInputRejected as exc:
        raise HTTPException(400, str(exc)) from exc
    except AccountMissing as exc:
        raise HTTPException(404, str(exc)) from exc
    except AccountUpdateConflict as exc:
        raise HTTPException(
            409,
            detail={
                "code": "account_conflict",
                "message": str(exc),
                "current_updated_at": exc.current_updated_at,
            },
        ) from exc
    except CandidateVerificationTimedOut as exc:
        raise HTTPException(504, "candidate verification timed out") from exc
    except CandidateVerificationFailed as exc:
        raise HTTPException(502, "candidate verification failed") from exc
