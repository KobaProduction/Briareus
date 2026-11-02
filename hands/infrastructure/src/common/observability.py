"""Compatibility exports for the canonical shared technical module."""

from service_runtime.observability import (
    AdminApiAuditSink as AdminApiAuditSink,
)
from service_runtime.observability import (
    CompositeObservabilitySink as CompositeObservabilitySink,
)
from service_runtime.observability import (
    ObservabilitySink as ObservabilitySink,
)
from service_runtime.observability import (
    OpenTelemetrySink as OpenTelemetrySink,
)
from service_runtime.observability import (
    announce_runtime_started as announce_runtime_started,
)
from service_runtime.observability import (
    build_observability as build_observability,
)
from service_runtime.observability import (
    otlp_headers as otlp_headers,
)
from service_runtime.observability import (
    resource_attributes as resource_attributes,
)
from service_runtime.observability import (
    telemetry_resource as telemetry_resource,
)
