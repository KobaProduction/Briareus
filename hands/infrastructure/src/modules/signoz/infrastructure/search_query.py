"""Compatibility exports for the shared provider implementation."""

from infrastructure_runtime.providers.signoz.infrastructure.search_query import (
    _TRACE_FIELDS as _TRACE_FIELDS,
)
from infrastructure_runtime.providers.signoz.infrastructure.search_query import (
    search_query as search_query,
)
from modules.signoz.domain.search import TelemetrySearch as TelemetrySearch

from .query_contracts import BuilderQuery as BuilderQuery
from .query_contracts import CompositeQuery as CompositeQuery
from .query_contracts import Expression as Expression
from .query_contracts import FormatOptions as FormatOptions
from .query_contracts import LogsBuilder as LogsBuilder
from .query_contracts import OrderBy as OrderBy
from .query_contracts import QueryField as QueryField
from .query_contracts import QueryRangeRequest as QueryRangeRequest
from .query_contracts import TracesBuilder as TracesBuilder
