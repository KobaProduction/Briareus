"""Compatibility exports of resource scope models, policy and JSONB decoding."""

from authorization.application.resource_receipts import (
    EffectResource as EffectResource,
)
from authorization.application.resource_receipts import (
    HandName as HandName,
)
from authorization.application.resource_receipts import (
    TrustedResourceOwnerPort as TrustedResourceOwnerPort,
)
from authorization.application.resource_receipts import (
    VerifiedResourceOwnerProof as VerifiedResourceOwnerProof,
)
from authorization.infrastructure.resource_scopes import (
    matches_current_owner as matches_current_owner,
)
from authorization.infrastructure.resource_scopes import (
    normalized_resource_grants as normalized_resource_grants,
)
from authorization.infrastructure.resource_scopes import (
    resource_key as resource_key,
)
from authorization.infrastructure.resource_scopes import (
    stored_grant_matches as stored_grant_matches,
)
from authorization.infrastructure.resource_scopes import (
    validate_effect_scope as validate_effect_scope,
)
from authorization.infrastructure.resource_scopes import (
    validate_project_resource_scope as validate_project_resource_scope,
)
from authorization.infrastructure.resource_scopes import (
    validate_resource_scope as validate_resource_scope,
)
