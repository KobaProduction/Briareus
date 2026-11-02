"""Adapt the existing logs/traces search to Query Builder's concrete variants."""

from infrastructure_runtime.providers.signoz.domain.search import TelemetrySearch

from .query_contracts import (
    BuilderQuery,
    CompositeQuery,
    Expression,
    FormatOptions,
    LogsBuilder,
    OrderBy,
    QueryField,
    QueryRangeRequest,
    TracesBuilder,
)

_TRACE_FIELDS = (
    ("timestamp", "number", "span"),
    ("trace_id", "string", "span"),
    ("span_id", "string", "span"),
    ("parent_span_id", "string", "span"),
    ("name", "string", "span"),
    ("service.name", "string", "resource"),
    ("kind_string", "string", "span"),
    ("duration_nano", "number", "span"),
    ("has_error", "bool", "span"),
    ("status_code_string", "string", "span"),
    ("status_message", "string", "span"),
    ("response_status_code", "string", "span"),
    ("http_method", "string", "span"),
)


def search_query(search: TelemetrySearch) -> QueryRangeRequest:
    spec: LogsBuilder | TracesBuilder
    if search.signal == "logs":
        spec = LogsBuilder(
            name="A",
            signal="logs",
            disabled=False,
            filter=Expression(expression=search.expression),
            limit=search.limit,
            offset=search.offset,
            having=Expression(expression=""),
            order=[
                OrderBy(key=QueryField(name=key), direction="desc") for key in ("timestamp", "id")
            ],
        )
    else:
        spec = TracesBuilder(
            name="A",
            signal="traces",
            disabled=False,
            filter=Expression(expression=search.expression),
            limit=search.limit,
            offset=search.offset,
            having=Expression(expression=""),
            order=[OrderBy(key=QueryField(name="timestamp"), direction="desc")],
            select_fields=[
                QueryField(
                    name=name, field_data_type=data_type, signal="traces", field_context=context
                )
                for name, data_type, context in _TRACE_FIELDS
            ],
        )
    return QueryRangeRequest(
        schema_version="v1",
        start=search.start_ms,
        end=search.end_ms,
        request_type="raw",
        composite_query=CompositeQuery(queries=[BuilderQuery(type="builder_query", spec=spec)]),
        format_options=FormatOptions(format_table_result_for_ui=False, fill_gaps=False),
        variables={},
    )
