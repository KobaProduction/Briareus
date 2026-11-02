"""Compatible exports for legacy provider validation; implementation owned by infrastructure."""

from projects.infrastructure.provider_validation import (
    GitHubOptions as GitHubOptions,
)
from projects.infrastructure.provider_validation import (
    GitLabOptions as GitLabOptions,
)
from projects.infrastructure.provider_validation import (
    InfrastructureOptions as InfrastructureOptions,
)
from projects.infrastructure.provider_validation import (
    ProviderDefinition as ProviderDefinition,
)
from projects.infrastructure.provider_validation import (
    ProviderOptions as ProviderOptions,
)
from projects.infrastructure.provider_validation import (
    provider_auth_types as provider_auth_types,
)
from projects.infrastructure.provider_validation import (
    provider_names as provider_names,
)
from projects.infrastructure.provider_validation import (
    validate_provider as validate_provider,
)
