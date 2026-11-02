"""Concrete private-cache fact; a cached answer stays bound to its OAuth context."""

from pydantic import BaseModel, ConfigDict, StrictBool


class OAuthContextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    oauth_session_id: str
    user_id: str
    blocked: StrictBool

    def matches(self, oauth_session_id: str, user_id: str) -> bool:
        return self.oauth_session_id == oauth_session_id and self.user_id == user_id
