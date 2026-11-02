"""Native MCP output schema metadata; no provider document is modeled or retained here."""

from pydantic.json_schema import JsonSchemaValue

# An empty JSON Schema accepts every JSON value, just as the former recursive
# union did. The object/envelope requirements and runtime validation stay intact.
JSON_OBJECT_OUTPUT_SCHEMA: JsonSchemaValue = {"type": "object", "additionalProperties": {}}
WRAPPED_PROVIDER_RESULT_SCHEMA: JsonSchemaValue = {
    "type": "object",
    "properties": {"result": {}},
    "required": ["result"],
    "x-fastmcp-wrap-result": True,
}
