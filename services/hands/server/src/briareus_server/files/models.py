from __future__ import annotations

from briareus_json_values import StrictModel


class ClientFile(StrictModel):
    download_url: str
    file_id: str | None = None
    mime_type: str | None = None
    file_name: str | None = None
