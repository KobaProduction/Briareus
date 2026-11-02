"""Docker seccomp boundary models for the pinned Chromium sandbox profile."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SeccompModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)


class SeccompArchitecture(SeccompModel):
    architecture: str
    sub_architectures: list[str] = Field(alias="subArchitectures")


class SeccompConditions(SeccompModel):
    caps: list[str] = Field(default_factory=list)
    arches: list[str] = Field(default_factory=list)
    min_kernel: str | None = Field(default=None, alias="minKernel")


class SeccompArgument(SeccompModel):
    index: int
    value: int
    value_two: int = Field(alias="valueTwo")
    op: Literal["SCMP_CMP_EQ", "SCMP_CMP_MASKED_EQ"]


class SeccompRule(SeccompModel):
    names: list[str]
    action: Literal["SCMP_ACT_ALLOW", "SCMP_ACT_ERRNO"]
    errno_ret: int | None = Field(default=None, alias="errnoRet")
    args: list[SeccompArgument] | None = None
    comment: str = ""
    includes: SeccompConditions = Field(default_factory=SeccompConditions)
    excludes: SeccompConditions = Field(default_factory=SeccompConditions)


class BrowserSeccompProfile(SeccompModel):
    default_action: str = Field(alias="defaultAction")
    architectures: list[SeccompArchitecture] = Field(alias="archMap")
    syscalls: list[SeccompRule]
