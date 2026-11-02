"""Compatibility exports for the shared provider implementation."""

from typing import Annotated as Annotated
from typing import Literal as Literal

from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict
from pydantic import Field as Field
from pydantic import StrictBool as StrictBool
from pydantic import StrictFloat as StrictFloat
from pydantic import StrictInt as StrictInt

from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    AiBuilderQuery as AiBuilderQuery,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    AiBuilderSpec as AiBuilderSpec,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    BucketOptions as BucketOptions,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    Builder as Builder,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    BuilderQuery as BuilderQuery,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    BuilderSpec as BuilderSpec,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    ClickHouseQuery as ClickHouseQuery,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    ComparisonAggregation as ComparisonAggregation,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    CompositeQuery as CompositeQuery,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    Expression as Expression,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    ExpressionAggregation as ExpressionAggregation,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    FormatOptions as FormatOptions,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    FormulaQuery as FormulaQuery,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    FormulaSpec as FormulaSpec,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    FunctionArgument as FunctionArgument,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    JoinQuery as JoinQuery,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    JoinSpec as JoinSpec,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    LimitBy as LimitBy,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    LinearBuckets as LinearBuckets,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    LinearBucketsSpec as LinearBucketsSpec,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    LogBuckets as LogBuckets,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    LogBucketsSpec as LogBucketsSpec,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    LogsBuilder as LogsBuilder,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    MetricAggregation as MetricAggregation,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    MetricsBuilder as MetricsBuilder,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    OrderBy as OrderBy,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    PromQlQuery as PromQlQuery,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    PromQlSpec as PromQlSpec,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    QueryContract as QueryContract,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    QueryEnvelope as QueryEnvelope,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    QueryField as QueryField,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    QueryFunction as QueryFunction,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    QueryModifiers as QueryModifiers,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    QueryRangeRequest as QueryRangeRequest,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    QueryRef as QueryRef,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    QuerySpec as QuerySpec,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    QueryVariable as QueryVariable,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    SecondaryAggregation as SecondaryAggregation,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    ServicesQuery as ServicesQuery,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    TextQuerySpec as TextQuerySpec,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    TraceOperatorQuery as TraceOperatorQuery,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    TraceOperatorSpec as TraceOperatorSpec,
)
from infrastructure_runtime.providers.signoz.infrastructure.query_contracts import (
    TracesBuilder as TracesBuilder,
)

from .discovery import TelemetryField as TelemetryField
