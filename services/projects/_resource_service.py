"""Compatible legacy resource service exports; concrete SQL adapter lives in infrastructure."""

from projects.infrastructure.resource_service import (
    ResourceService as ResourceService,
)
from projects.infrastructure.resource_service import (
    ResourceSettings as ResourceSettings,
)
from projects.infrastructure.resource_service import (
    owner_of as owner_of,
)
from projects.infrastructure.resource_service import (
    utcnow as utcnow,
)
from projects.infrastructure.resource_service import (
    view_of as view_of,
)
