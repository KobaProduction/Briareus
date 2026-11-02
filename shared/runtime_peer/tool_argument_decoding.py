"""Native argument validation against a concrete tool-to-record schema index."""

from collections.abc import Mapping

from pydantic import BaseModel, ValidationInfo


def selected_tool(info: ValidationInfo[object]) -> str:
    tool = info.data.get("tool")
    if not isinstance(tool, str):
        raise ValueError("Tool name required")
    return tool


def decode_tool_arguments[ArgumentsT: BaseModel](
    tool: str, value: object, models: Mapping[str, type[ArgumentsT]]
) -> ArgumentsT:
    try:
        model = models[tool]
    except KeyError:
        raise ValueError("Known tool argument schema required") from None
    if isinstance(value, model):
        return value
    if not isinstance(value, dict) or len(value) > 16:
        raise ValueError("Bounded tool arguments required")
    return model.model_validate(value)
