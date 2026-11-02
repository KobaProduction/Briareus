"""Concrete private headers and real SDK catalogue descriptors."""

from fastmcp.tools import Tool as MetadataTool
from pydantic import UUID4, BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt

from hand_runtime.private_call import PrivateToolCall
from serena_hand.domain.effects import EffectAuthority
from serena_hand.domain.session import SessionCatalogue


def _foreground(value: bool) -> bool:
    return not value


class PrivateRequest(PrivateToolCall):
    id: UUID4
    expires_at: StrictFloat | StrictInt
    background: StrictBool = Field(default=False, exclude_if=_foreground)

    def authority(self) -> EffectAuthority:
        return EffectAuthority(self.id, self.call.name, float(self.expires_at), self.background)


class ReadyCatalogue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ready: StrictBool
    tools: list[MetadataTool]

    def validate_catalogue(self) -> None:
        if not self.ready:
            raise ValueError("Actual Serena runtime readiness required")
        SessionCatalogue(tuple(tool.name for tool in self.tools))
