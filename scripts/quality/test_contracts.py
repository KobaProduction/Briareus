"""Critical checks for the quality gate itself, using disposable source fixtures."""

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import contracts


@dataclass(frozen=True)
class Case:
    code: str
    blocked: bool


def test_result_contracts(tmp_path: Path) -> None:
    cases = [
        Case("def f() -> dict[str, int]:\n return {}", True),
        Case("def f():\n result = dict(a=1)\n return result", True),
        Case("from typing import Dict as Payload\ndef f() -> 'Payload[str, int]':\n pass", True),
        Case("type Payload = dict[str, int]\ndef f() -> Payload:\n pass", True),
        Case("callback = lambda: dict(count=1)", True),
        Case("def f(value: dict[str, int]) -> object:\n return value", True),
        Case("def f(**values: int) -> object:\n return values", True),
        Case(
            "from typing import NamedTuple\nResult = NamedTuple('Result', [('data', dict)])\n"
            "def f() -> Result:\n return Result({})",
            False,
        ),
        Case(
            "from dataclasses import dataclass\n@dataclass\nclass Result:\n count: int\n"
            "def f() -> Result:\n return Result(1)",
            False,
        ),
        Case("def outer() -> int:\n def inner() -> dict:\n  return {}\n return 1", True),
    ]
    with patch.object(contracts, "ROOT", tmp_path):
        for case in cases:
            (tmp_path / "sample.py").write_text(case.code, encoding="utf-8")
            assert bool(contracts.contract_findings("sample.py")) is case.blocked


def test_real_cognitive_thresholds(tmp_path: Path) -> None:
    config = "[tool.briareus-quality]\ncognitive-production=15\ncognitive-tests=30\n"
    (tmp_path / "pyproject.toml").write_text(config)
    code = (
        "def f(x: int) -> int:\n"
        + "".join(" " * (level + 1) + "if x:\n" for level in range(6))
        + "       return x\n return 0\n"
    )
    (tmp_path / "sample.py").write_text(code)
    (tmp_path / "test_sample.py").write_text(code)
    with patch.object(contracts, "ROOT", tmp_path):
        assert contracts.complexity_findings("sample.py")
        assert not contracts.complexity_findings("test_sample.py")
