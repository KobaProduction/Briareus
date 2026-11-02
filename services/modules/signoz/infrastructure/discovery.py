"""Compatibility exports for the shared provider implementation."""

from pydantic import Field as Field
from pydantic import StrictBool as StrictBool
from pydantic import StrictFloat as StrictFloat
from pydantic import StrictInt as StrictInt

from common.provider_identity import ProviderMetadata as ProviderMetadata
from common.provider_identity import SigNozReply as SigNozReply
from common.provider_identity import unreported as unreported
from infrastructure_runtime.providers.signoz.infrastructure.discovery import (
    FieldCatalogue as FieldCatalogue,
)
from infrastructure_runtime.providers.signoz.infrastructure.discovery import (
    FieldKeysQuery as FieldKeysQuery,
)
from infrastructure_runtime.providers.signoz.infrastructure.discovery import (
    FieldKeysReply as FieldKeysReply,
)
from infrastructure_runtime.providers.signoz.infrastructure.discovery import (
    FieldValues as FieldValues,
)
from infrastructure_runtime.providers.signoz.infrastructure.discovery import (
    FieldValuesQuery as FieldValuesQuery,
)
from infrastructure_runtime.providers.signoz.infrastructure.discovery import (
    FieldValuesReply as FieldValuesReply,
)
from infrastructure_runtime.providers.signoz.infrastructure.discovery import (
    TelemetryField as TelemetryField,
)
from infrastructure_runtime.providers.signoz.infrastructure.discovery import (
    TelemetryValues as TelemetryValues,
)
