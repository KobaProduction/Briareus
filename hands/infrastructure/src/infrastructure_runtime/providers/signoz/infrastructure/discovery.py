"""SigNoz field-discovery models from the provider OpenAPI definitions."""

from pydantic import Field, StrictBool, StrictFloat, StrictInt

from service_runtime.provider_identity import ProviderMetadata, SigNozReply, unreported


class TelemetryField(ProviderMetadata):
    name: str
    description: str | None = Field(default=None, exclude_if=unreported)
    field_context: str | None = Field(default=None, alias="fieldContext", exclude_if=unreported)
    field_data_type: str | None = Field(default=None, alias="fieldDataType", exclude_if=unreported)
    signal: str | None = Field(default=None, exclude_if=unreported)
    unit: str | None = Field(default=None, exclude_if=unreported)


class FieldCatalogue(ProviderMetadata):
    complete: StrictBool
    keys: dict[str, list[TelemetryField]] | None


class TelemetryValues(ProviderMetadata):
    bool_values: list[StrictBool] | None = Field(
        default=None, alias="boolValues", exclude_if=unreported
    )
    number_values: list[StrictInt | StrictFloat] | None = Field(
        default=None, alias="numberValues", exclude_if=unreported
    )
    related_values: list[str] | None = Field(
        default=None, alias="relatedValues", exclude_if=unreported
    )
    string_values: list[str] | None = Field(
        default=None, alias="stringValues", exclude_if=unreported
    )


class FieldValues(ProviderMetadata):
    complete: StrictBool
    values: TelemetryValues


class FieldKeysQuery(ProviderMetadata):
    signal: str
    search_text: str | None = Field(default=None, alias="searchText")
    metric_name: str | None = Field(default=None, alias="metricName")


class FieldValuesQuery(FieldKeysQuery):
    name: str


class FieldKeysReply(SigNozReply[FieldCatalogue]):
    pass


class FieldValuesReply(SigNozReply[FieldValues]):
    pass
