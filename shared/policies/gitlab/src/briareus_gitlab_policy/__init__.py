from __future__ import annotations

from briareus_json_values import StrictModel


class GitLabRuntimePolicy(StrictModel):
    local_first_guidance: bool = True
    local_git_transport_enabled: bool = True
    remote_source_mutations_enabled: bool = False
