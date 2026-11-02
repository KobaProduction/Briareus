"""Versioned public provider metadata in the legacy Projects-owned JSONB column."""

from typing import Literal

from pydantic import ConfigDict

from runtime_peer.provider_settings import ProviderSettingsInput


class StoredProviderSettings(ProviderSettingsInput):
    # Existing v1 rows have no marker. New writes declare the same schema explicitly.
    model_config = ConfigDict(extra="ignore", frozen=True)
    schema_version: Literal[1] = 1
