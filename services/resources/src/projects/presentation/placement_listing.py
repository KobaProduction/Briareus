"""Serialize typed placement views using the existing public response shape."""

from dataclasses import asdict

from fastapi.responses import JSONResponse

from projects.application.placement_listing import PlacementView
from projects.presentation.placement_operation import PlacementOperationSummary


def placement_list_response(items: tuple[PlacementView, ...]) -> JSONResponse:
    result = []
    for item in items:
        value = asdict(item)
        value["limits"] = item.limits.model_dump(mode="json")
        value["configuration"] = (
            item.configuration.model_dump(mode="json") if item.configuration is not None else None
        )
        value["project_workspace"] = (
            item.project_workspace.model_dump(mode="json")
            if item.project_workspace is not None
            else None
        )
        if item.operation is not None:
            operation = PlacementOperationSummary.model_validate(
                item.operation, from_attributes=True
            )
            value["operation"] = operation.model_dump(mode="json", exclude_none=True) | {
                "error": operation.error
            }
        result.append(value)
    return JSONResponse({"items": result})
