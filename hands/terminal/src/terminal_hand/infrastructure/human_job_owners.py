"""Root-owned job authority; child metadata never proves a human owner."""

import json
import os
from pathlib import Path

from pydantic import UUID4, BaseModel, ConfigDict, Field

from terminal_hand.domain.human_principal import HumanOperationPrincipal
from terminal_hand.domain.operation import require_history_capacity


class SavedHumanJobOwner(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    job_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    actor_uuid: UUID4
    project_uuid: UUID4
    operation_uuid: UUID4
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class HumanJobOwners:
    def __init__(self, root: Path) -> None:
        self.root = root / "human-jobs"
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or self.root.stat().st_uid != 0:
            raise ValueError("Private supervisor job ownership required")
        os.chmod(self.root, 0o700)
        self._saved: dict[str, SavedHumanJobOwner] = {}
        for path in self.root.glob("*.json"):
            if path.is_symlink() or path.stat().st_uid != 0:
                raise ValueError("Private job ownership file required")
            saved = SavedHumanJobOwner.model_validate_json(path.read_bytes())
            if path.name != saved.job_id + ".json":
                raise ValueError("Job ownership filename changed")
            self._saved[saved.job_id] = saved

    def _read(self, job_id: str) -> SavedHumanJobOwner | None:
        if len(job_id) != 32 or any(char not in "0123456789abcdef" for char in job_id):
            return None
        return self._saved.get(job_id)

    def require(self, principal: HumanOperationPrincipal, job_id: str) -> None:
        saved = self._read(job_id)
        if saved is None or (saved.actor_uuid, saved.project_uuid) != (
            principal.actor_uuid,
            principal.project_uuid,
        ):
            raise ValueError("Job is not owned by the current project user")

    def allowed(self, principal: HumanOperationPrincipal) -> tuple[str, ...]:
        return tuple(
            item.job_id
            for item in self._saved.values()
            if (item.actor_uuid, item.project_uuid)
            == (principal.actor_uuid, principal.project_uuid)
        )

    def bind(self, principal: HumanOperationPrincipal, fingerprint: str) -> str:
        job_id = principal.operation_uuid.hex
        saved = SavedHumanJobOwner(
            job_id=job_id,
            actor_uuid=principal.actor_uuid,
            project_uuid=principal.project_uuid,
            operation_uuid=principal.operation_uuid,
            fingerprint=fingerprint,
        )
        previous = self._read(job_id)
        if previous is not None:
            if previous != saved:
                raise ValueError("Job operation identity reused with another owner")
            return job_id
        require_history_capacity(len(self._saved))
        with (self.root / (job_id + ".json")).open("x") as file:
            os.chmod(file.name, 0o600)
            json.dump(saved.model_dump(mode="json"), file)
            file.flush()
            os.fsync(file.fileno())
        self._saved[job_id] = saved
        return job_id
