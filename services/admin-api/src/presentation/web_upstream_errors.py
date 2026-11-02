"""Translate retained administration upstream failures at the HTTP boundary."""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException


@contextmanager
def web_upstream_errors() -> Iterator[None]:
    try:
        yield
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
