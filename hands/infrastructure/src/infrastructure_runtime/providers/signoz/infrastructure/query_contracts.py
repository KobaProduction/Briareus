"""SigNoz Query Builder v5 variants, from provider commit 9ba2a25eb98a.

Source: SigNoz/signoz/pkg/types/querybuildertypes/querybuildertypesv5.
Query field keys reuse the field-discovery contract. Unknown request options
fail validation rather than disappearing during serialization.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt

from .discovery import TelemetryField


class QueryContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
        hide_input_in_errors=True,
    )


class QueryField(TelemetryField):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Expression(QueryContract):
    expression: str


class ExpressionAggregation(Expression):
    alias: str | None = None


class ComparisonAggregation(QueryContract):
    operator: str
    threshold: StrictFloat


class MetricAggregation(QueryContract):
    metric_name: str = Field(alias="metricName")
    temporality: str | None = None
    time_aggregation: str | None = Field(default=None, alias="timeAggregation")
    space_aggregation: str | None = Field(default=None, alias="spaceAggregation")
    comparison_space_aggregation_param: ComparisonAggregation | None = Field(
        default=None, alias="comparisonSpaceAggregationParam"
    )
    reduce_to: str | None = Field(default=None, alias="reduceTo")


class OrderBy(QueryContract):
    key: QueryField
    direction: Literal["asc", "desc"]


class LimitBy(QueryContract):
    keys: list[str]
    value: str


class FunctionArgument(QueryContract):
    name: str | None = None
    value: str | StrictInt | StrictFloat | StrictBool


class QueryFunction(QueryContract):
    name: str
    args: list[FunctionArgument] | None = None


class LinearBucketsSpec(QueryContract):
    max_value: StrictFloat = Field(alias="maxValue")
    num_buckets: StrictInt | None = Field(default=None, alias="numBuckets")


class LogBucketsSpec(QueryContract):
    scale: StrictInt | None = None


class LinearBuckets(QueryContract):
    kind: Literal["linear"]
    spec: LinearBucketsSpec


class LogBuckets(QueryContract):
    kind: Literal["log"]
    spec: LogBucketsSpec


type BucketOptions = Annotated[LinearBuckets | LogBuckets, Field(discriminator="kind")]


class SecondaryAggregation(ExpressionAggregation):
    step_interval: str | StrictInt | StrictFloat | None = Field(default=None, alias="stepInterval")
    group_by: list[QueryField] | None = Field(default=None, alias="groupBy")
    order: list[OrderBy] | None = None
    limit: StrictInt | None = None
    limit_by: LimitBy | None = Field(default=None, alias="limitBy")


class QuerySpec(QueryContract):
    name: str
    disabled: StrictBool | None = None


class QueryModifiers(QuerySpec):
    filter: Expression | None = None
    group_by: list[QueryField] | None = Field(default=None, alias="groupBy")
    order: list[OrderBy] | None = None
    select_fields: list[QueryField] | None = Field(default=None, alias="selectFields")
    limit: StrictInt | None = None
    having: Expression | None = None
    functions: list[QueryFunction] | None = None


class BuilderSpec(QueryModifiers):
    legend: str | None = None
    source: str | None = None
    step_interval: str | StrictInt | StrictFloat | None = Field(default=None, alias="stepInterval")
    bucket_options: BucketOptions | None = Field(default=None, alias="bucketOptions")
    limit_by: LimitBy | None = Field(default=None, alias="limitBy")
    offset: StrictInt | None = None
    cursor: str | None = None
    secondary_aggregations: list[SecondaryAggregation] | None = Field(
        default=None, alias="secondaryAggregations"
    )


class LogsBuilder(BuilderSpec):
    signal: Literal["logs"]
    aggregations: list[ExpressionAggregation] | None = None


class TracesBuilder(BuilderSpec):
    signal: Literal["traces"]
    aggregations: list[ExpressionAggregation] | None = None


class MetricsBuilder(BuilderSpec):
    signal: Literal["metrics"]
    aggregations: list[MetricAggregation] | None = None


type Builder = Annotated[
    LogsBuilder | TracesBuilder | MetricsBuilder, Field(discriminator="signal")
]


class BuilderQuery(QueryContract):
    type: Literal["builder_query", "builder_sub_query"]
    spec: Builder


class AiBuilderSpec(BuilderSpec):
    signal: Literal["traces"] | None = None
    aggregations: list[ExpressionAggregation] | None = None


class AiBuilderQuery(QueryContract):
    type: Literal["builder_ai_query"]
    spec: AiBuilderSpec


class FormulaSpec(QuerySpec):
    legend: str | None = None
    expression: str
    order: list[OrderBy] | None = None
    limit: StrictInt | None = None
    having: Expression | None = None
    functions: list[QueryFunction] | None = None
    bucket_options: BucketOptions | None = Field(default=None, alias="bucketOptions")


class FormulaQuery(QueryContract):
    type: Literal["builder_formula"]
    spec: FormulaSpec


class QueryRef(QueryContract):
    name: str


class JoinSpec(QueryModifiers):
    left: QueryRef
    right: QueryRef
    type: Literal["inner", "left", "right", "full", "cross"]
    on: str
    aggregations: list[ExpressionAggregation | MetricAggregation] | None = None
    secondary_aggregations: list[SecondaryAggregation] | None = Field(
        default=None, alias="secondaryAggregations"
    )


class JoinQuery(QueryContract):
    type: Literal["builder_join"]
    spec: JoinSpec


class TraceOperatorSpec(QueryModifiers):
    legend: str | None = None
    expression: str
    return_spans_from: str | None = Field(default=None, alias="returnSpansFrom")
    step_interval: str | StrictInt | StrictFloat | None = Field(default=None, alias="stepInterval")
    aggregations: list[ExpressionAggregation] | None = None
    offset: StrictInt | None = None
    cursor: str | None = None


class TraceOperatorQuery(QueryContract):
    type: Literal["builder_trace_operator"]
    spec: TraceOperatorSpec


class TextQuerySpec(QuerySpec):
    legend: str | None = None
    query: str


class PromQlSpec(TextQuerySpec):
    step: str | StrictInt | StrictFloat | None = None
    stats: StrictBool | None = None


class PromQlQuery(QueryContract):
    type: Literal["promql"]
    spec: PromQlSpec


class ClickHouseQuery(QueryContract):
    type: Literal["clickhouse_sql"]
    spec: TextQuerySpec


type QueryEnvelope = Annotated[
    BuilderQuery
    | AiBuilderQuery
    | FormulaQuery
    | JoinQuery
    | TraceOperatorQuery
    | PromQlQuery
    | ClickHouseQuery,
    Field(discriminator="type"),
]


class CompositeQuery(QueryContract):
    queries: list[QueryEnvelope]


class QueryVariable(QueryContract):
    type: Literal["query", "dynamic", "custom", "text"]
    value: (
        str
        | StrictInt
        | StrictFloat
        | StrictBool
        | list[str | StrictInt | StrictFloat | StrictBool | None]
        | None
    )


class FormatOptions(QueryContract):
    fill_gaps: StrictBool | None = Field(default=None, alias="fillGaps")
    format_table_result_for_ui: StrictBool | None = Field(
        default=None, alias="formatTableResultForUI"
    )


class QueryRangeRequest(QueryContract):
    schema_version: str | None = Field(default=None, alias="schemaVersion")
    start: StrictInt = Field(ge=0, lt=2**64)
    end: StrictInt = Field(ge=0, lt=2**64)
    request_type: Literal[
        "scalar", "time_series", "raw", "raw_stream", "trace", "distribution", "heatmap"
    ] = Field(alias="requestType")
    composite_query: CompositeQuery = Field(alias="compositeQuery")
    variables: dict[str, QueryVariable] | None = None
    no_cache: StrictBool | None = Field(default=None, alias="noCache")
    format_options: FormatOptions | None = Field(default=None, alias="formatOptions")


class ServicesQuery(QueryContract):
    start: str
    end: str
