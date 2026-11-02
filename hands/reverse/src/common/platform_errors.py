"""Application errors; HTTP adaptation must preserve Admin API v1 envelope."""

from __future__ import annotations

from service_runtime.platform_errors import (
    AccessDenied as AccessDenied,
)
from service_runtime.platform_errors import (
    AuthenticationRateLimited as AuthenticationRateLimited,
)
from service_runtime.platform_errors import (
    AuthenticationRequired as AuthenticationRequired,
)
from service_runtime.platform_errors import (
    Conflict as Conflict,
)
from service_runtime.platform_errors import (
    IdempotencyConflict as IdempotencyConflict,
)
from service_runtime.platform_errors import (
    InvalidInput as InvalidInput,
)
from service_runtime.platform_errors import (
    InvalidInvitation as InvalidInvitation,
)
from service_runtime.platform_errors import (
    LastSuperuser as LastSuperuser,
)
from service_runtime.platform_errors import (
    OperationInProgress as OperationInProgress,
)
from service_runtime.platform_errors import (
    PersistenceTimeout as PersistenceTimeout,
)
from service_runtime.platform_errors import (
    PlatformError as PlatformError,
)
from service_runtime.platform_errors import (
    ResourceMissing as ResourceMissing,
)
