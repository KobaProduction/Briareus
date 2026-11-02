"""Versioned public provider metadata in Resources' independently owned JSONB."""

from typing import Literal

from pydantic import ConfigDict

from runtime_peer.provider_settings import ProviderSettingsInput


class StoredProviderSettings(ProviderSettingsInput):
    model_config = ConfigDict(extra="ignore", frozen=True)
    schema_version: Literal[1] = 1
