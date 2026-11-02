"""Closed JSON Schema grammar emitted by the existing provider connection forms.

These are form definitions, never connection values or credentials. Field-name
and definition-name indexes contain validated schema nodes, not arbitrary JSON.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FormSchemaNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    reference: str | None = Field(default=None, alias="$ref")
    type: Literal["object", "array", "string", "integer", "number", "boolean", "null"] | None = None
    title: str | None = None
    description: str | None = None
    format: str | None = None
    const: str | int | float | bool | None = None
    enum: tuple[str, ...] | None = None
    default: str | int | float | bool | None = None
    properties: dict[str, FormSchemaNode] | None = None
    required: tuple[str, ...] | None = None
    additionalProperties: bool | None = None
    items: FormSchemaNode | None = None
    anyOf: tuple[FormSchemaNode, ...] | None = None
    minLength: int | None = Field(default=None, ge=0)
    maxLength: int | None = Field(default=None, ge=0)
    minItems: int | None = Field(default=None, ge=0)
    maxItems: int | None = Field(default=None, ge=0)
    writeOnly: bool | None = None


class FormDiscriminator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    propertyName: Literal["provider"]
    mapping: dict[str, str]


class ConnectionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    definitions: dict[str, FormSchemaNode] = Field(alias="$defs")
    discriminator: FormDiscriminator
    oneOf: tuple[FormSchemaNode, ...]
