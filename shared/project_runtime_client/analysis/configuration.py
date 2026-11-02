"""Readonly provider configuration supplied by owner composition."""

from typing import Protocol


class AnalysisBackendConfiguration(Protocol):
    @property
    def backend_url(self) -> str: ...

    @property
    def schema_cache_ttl_seconds(self) -> float: ...

    @property
    def direct_upload_url(self) -> str: ...

    @property
    def direct_upload_timeout_seconds(self) -> float: ...
