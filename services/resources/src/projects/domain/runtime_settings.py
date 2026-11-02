"""An omitted override inherits; an explicit null disables that runtime setting."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from uuid import UUID


class RuntimePolicyConflict(ValueError):
    pass


class RuntimePolicyForbidden(ValueError):
    pass


class RuntimeNodeMissing(ValueError):
    pass


class RuntimeSetting(StrEnum):
    EXECUTION_TIMEOUT = "execution_timeout_seconds"
    WEB_MAX_TABS = "web_max_tabs"
    WEB_TAB_IDLE = "web_tab_idle_seconds"
    TERMINAL_IDLE = "terminal_idle_seconds"


class RuntimeSource(StrEnum):
    DEFAULT = "default"
    SERVER = "server"
    NODE = "node"


type RuntimeValue = float | int | None
type RuntimeScope = Literal["server", "node"]


@dataclass(frozen=True)
class RuntimeOverride:
    setting: RuntimeSetting
    value: RuntimeValue


@dataclass(frozen=True)
class RuntimeOverrides:
    entries: tuple[RuntimeOverride, ...] = ()

    def __post_init__(self) -> None:
        if len({entry.setting for entry in self.entries}) != len(self.entries):
            raise ValueError("A runtime setting can be overridden only once per scope")

    def find(self, setting: RuntimeSetting) -> RuntimeOverride | None:
        return next((entry for entry in self.entries if entry.setting == setting), None)


@dataclass(frozen=True)
class EffectiveSetting:
    setting: RuntimeSetting
    value: RuntimeValue
    source: RuntimeSource


@dataclass(frozen=True)
class RuntimeResolution:
    entries: tuple[EffectiveSetting, ...]


def resolve_runtime(server: RuntimeOverrides, node: RuntimeOverrides) -> RuntimeResolution:
    defaults = (
        RuntimeOverride(RuntimeSetting.EXECUTION_TIMEOUT, None),
        RuntimeOverride(RuntimeSetting.WEB_MAX_TABS, 10),
        RuntimeOverride(RuntimeSetting.WEB_TAB_IDLE, None),
        RuntimeOverride(RuntimeSetting.TERMINAL_IDLE, None),
    )
    return RuntimeResolution(tuple(resolve_setting(entry, server, node) for entry in defaults))


def resolve_setting(
    default: RuntimeOverride, server: RuntimeOverrides, node: RuntimeOverrides
) -> EffectiveSetting:
    inherited = server.find(default.setting)
    selected = node.find(default.setting)
    if selected is not None:
        return EffectiveSetting(selected.setting, selected.value, RuntimeSource.NODE)
    if inherited is not None:
        return EffectiveSetting(inherited.setting, inherited.value, RuntimeSource.SERVER)
    return EffectiveSetting(default.setting, default.value, RuntimeSource.DEFAULT)


@dataclass(frozen=True)
class StoredRuntimePolicy:
    sequence: int
    overrides: RuntimeOverrides


@dataclass(frozen=True)
class RuntimePolicyView:
    scope: RuntimeScope
    node_uuid: UUID | None
    sequence: int
    overrides: RuntimeOverrides
    effective: RuntimeResolution


@dataclass(frozen=True)
class RuntimePolicyIdentity:
    operation_uuid: UUID
    actor_uuid: UUID
    project_uuid: UUID
    fingerprint: str
    expected_sequence: int | None
