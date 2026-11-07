from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from ._deployment import run_deployment
from ._models import ErrorCode, NodeRegistrationError, NodeSpec, RegistryConfig
from ._service import ensure_node
from ._zitadel import ZitadelRoleRegistry


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    origin: str
    issuer: str
    project: str
    provider: Literal["zitadel"]
    locale: Literal["ru", "en"]
    command: list[str] = Field(default_factory=list)


class _Messages(BaseModel):
    ru: dict[ErrorCode, str]
    en: dict[ErrorCode, str]


class _FailureOutput(BaseModel):
    status: Literal["error"] = "error"
    code: ErrorCode
    node: str
    http_status: int | None
    message: str


def arguments(argv: list[str] | None) -> _Arguments:
    values = sys.argv[1:] if argv is None else argv
    boundary = values.index("--") if "--" in values else len(values)
    parser = argparse.ArgumentParser(description="Ensure the node role before deployment.")
    parser.add_argument("--origin", required=True)
    parser.add_argument("--issuer", default=os.environ.get("OIDC_ISSUER_URL", ""))
    parser.add_argument("--project", default=os.environ.get("OIDC_AUDIENCE", ""))
    parser.add_argument("--provider", choices=("zitadel",), required=True)
    parser.add_argument("--locale", choices=("ru", "en"), default="ru")
    parsed = vars(parser.parse_args(values[:boundary]))
    return _Arguments.model_validate({**parsed, "command": values[boundary + 1 :]})


def failure(error: NodeRegistrationError, language: Literal["ru", "en"]) -> int:
    messages = _Messages.model_validate_json(Path(__file__).with_name("messages.json").read_bytes())
    translated = messages.en if language == "en" else messages.ru
    message = translated[error.code].format(node=error.node, status=error.status)
    print(
        _FailureOutput(
            code=error.code, node=error.node, http_status=error.status, message=message
        ).model_dump_json()
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    args = arguments(argv)
    try:
        node = NodeSpec(origin=args.origin)
        config = RegistryConfig(
            issuer=args.issuer,
            project_id=args.project,
            token=SecretStr(os.environ.get("ZITADEL_PROVISIONING_TOKEN", "")),
        )
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            result = ensure_node(node, ZitadelRoleRegistry(config, client))
        print(result.model_dump_json(by_alias=True), flush=True)
        if run_deployment(args.command, node):
            return failure(NodeRegistrationError(ErrorCode.DEPLOYMENT, node.node_id), args.locale)
        return 0
    except ValidationError:
        return failure(NodeRegistrationError(ErrorCode.CONFIGURATION), args.locale)
    except NodeRegistrationError as error:
        return failure(error, args.locale)
