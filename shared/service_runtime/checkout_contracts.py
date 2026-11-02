"""Checkout effect receipt before provider-specific outward projection."""

from pydantic import BaseModel, ConfigDict


class RepositoryCheckout(BaseModel):
    model_config = ConfigDict(frozen=True)
    path: str
    resolved_path: str
    mode: str
    ref: str
    git_metadata: bool
    auth_mode: str
