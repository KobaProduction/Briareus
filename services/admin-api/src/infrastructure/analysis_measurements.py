"""Read-only projections used to calculate coverage, never forwarded as provider replies."""

from domain.analysis import FunctionDocumentation
from pydantic import BaseModel


class FunctionCount(BaseModel):
    function_count: int


class FunctionAddress(BaseModel):
    address: str | None = None


class FunctionListing(BaseModel):
    functions: list[FunctionAddress]


class FunctionQualityBatch(BaseModel):
    results: list[FunctionDocumentation]
