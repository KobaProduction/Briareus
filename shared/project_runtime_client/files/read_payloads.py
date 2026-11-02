"""Exact A14 canonical JSON preimage, with its original string encodings."""

from pydantic import BaseModel, ConfigDict


class NativeReadBusinessObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    content_sha256: str
    size_bytes: int
    inode_digest: str
    mount_scope_digest: str
    verified_uid: int
    observed_at: str


class FilesReadBusinessPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    file_id: str
    expected_file_version: int
    path_digest: str
    service_id: str
    instance_uuid: str
    native_observation: NativeReadBusinessObservation
