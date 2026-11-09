"""Public backend location for the Analyzer proxy."""

from briareus_environment_models import ProcessSettings
from pydantic import Field


class AnalyzerSettings(ProcessSettings):
    backend_url: str = Field(
        "http://radare2-mcp-hand:8000/mcp",
        min_length=1,
        validation_alias="RADARE2_MCP_URL",
    )
