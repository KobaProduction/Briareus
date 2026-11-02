"""Typed Analysis selectors and the complete external SDK call at transport boundaries."""

from typing import Literal, Self

from mcp_types import CallToolRequestParams
from pydantic import BaseModel, ConfigDict, ModelWrapValidatorHandler, model_validator

AnalysisEngine = Literal["ghidra", "radare2"]


class AnalysisArgumentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @property
    def preparation_engine(self) -> str | None:
        return None


class AnalysisCatalogueArguments(AnalysisArgumentRecord):
    engine: AnalysisEngine

    @property
    def preparation_engine(self) -> str:
        return self.engine


class AnalysisNativeArguments(AnalysisCatalogueArguments):
    """Bind an engine selector to a provider-owned MCP call, without copying its schema."""

    call: CallToolRequestParams

    @model_validator(mode="wrap")
    @classmethod
    def native_call(cls, value: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        if isinstance(value, cls):
            return handler(value)
        if not isinstance(value, dict):
            raise ValueError("Exact native Analysis arguments required")
        if (
            set(value) == {"engine", "call"}
            and isinstance(value["call"], CallToolRequestParams)
            and value["call"].arguments is not None
            and value["call"].model_fields_set <= {"name", "arguments"}
        ):
            return handler(value)
        if set(value) != {"engine", "tool", "arguments"} or not isinstance(
            value["arguments"], dict
        ):
            raise ValueError("Exact native Analysis arguments required")
        call = CallToolRequestParams.model_validate(
            {"name": value["tool"], "arguments": value["arguments"]}, strict=True
        )
        return handler({"engine": value["engine"], "call": call})


class AnalysisOperationArguments(AnalysisArgumentRecord):
    operation_id: str


type AnalysisArguments = (
    AnalysisCatalogueArguments | AnalysisNativeArguments | AnalysisOperationArguments
)

ANALYSIS_ARGUMENTS: dict[str, type[AnalysisArguments]] = {
    "analysis_tools": AnalysisCatalogueArguments,
    "analysis_call": AnalysisNativeArguments,
    "analysis_start": AnalysisNativeArguments,
    "analysis_poll": AnalysisOperationArguments,
    "analysis_cancel": AnalysisOperationArguments,
}
