"""Coverage sampling and documentation assessment independent of providers and transports."""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean


@dataclass(frozen=True, slots=True)
class CoverageRequest:
    project_id: str = ""
    program: str = ""
    full: bool = False

    def require_target(self) -> None:
        if not self.project_id:
            raise ValueError("cached coverage project_id is missing")
        if not self.program:
            raise ValueError("cached coverage program is missing")


@dataclass(frozen=True, slots=True)
class FunctionDocumentation:
    effective_score: float | None = None
    completeness_score: float | None = None
    has_custom_name: bool = False
    has_plate_comment: bool = False
    has_prototype: bool = False
    return_type_resolved: bool = False
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CoverageSelection:
    addresses: tuple[str, ...]
    approximate: bool


def select_coverage(addresses: Sequence[str], *, full: bool, sample_size: int) -> CoverageSelection:
    approximate = not full and len(addresses) > sample_size
    if not approximate:
        return CoverageSelection(tuple(addresses), False)
    target = max(1, sample_size)
    if target == 1:
        selected = tuple(addresses[:1])
    else:
        last = len(addresses) - 1
        indices = {round(index * last / (target - 1)) for index in range(target)}
        selected = tuple(addresses[index] for index in sorted(indices))
    return CoverageSelection(selected, True)


@dataclass(frozen=True, slots=True)
class CoverageReport:
    project_id: str
    program: str
    total_functions: int
    evaluated_functions: int
    approximate: bool
    sample_size: int
    average_effective_score: float
    average_raw_score: float
    complete_80_plus: int
    complete_80_plus_percent: float
    strong_60_79: int
    strong_60_79_percent: float
    partial_40_59: int
    partial_40_59_percent: float
    low_under_40: int
    low_under_40_percent: float
    custom_named: int
    plate_documented: int
    prototype_set: int
    return_type_resolved: int


def _percentage(count: int, total: int) -> float:
    return round(count * 100.0 / total, 1) if total else 0.0


def assess_coverage(
    project_id: str,
    program: str,
    *,
    total_functions: int,
    selection: CoverageSelection,
    results: Sequence[FunctionDocumentation],
) -> CoverageReport:
    scores = [item.effective_score for item in results if item.effective_score is not None]
    raw_scores = [
        item.completeness_score for item in results if item.completeness_score is not None
    ]
    complete = sum(score >= 80 for score in scores)
    strong = sum(60 <= score < 80 for score in scores)
    partial = sum(40 <= score < 60 for score in scores)
    low = sum(score < 40 for score in scores)
    evaluated = len(scores)
    return CoverageReport(
        project_id=project_id,
        program=program,
        total_functions=total_functions,
        evaluated_functions=evaluated,
        approximate=selection.approximate,
        sample_size=len(selection.addresses),
        average_effective_score=round(fmean(scores), 1) if scores else 0.0,
        average_raw_score=round(fmean(raw_scores), 1) if raw_scores else 0.0,
        complete_80_plus=complete,
        complete_80_plus_percent=_percentage(complete, evaluated),
        strong_60_79=strong,
        strong_60_79_percent=_percentage(strong, evaluated),
        partial_40_59=partial,
        partial_40_59_percent=_percentage(partial, evaluated),
        low_under_40=low,
        low_under_40_percent=_percentage(low, evaluated),
        custom_named=sum(item.has_custom_name for item in results),
        plate_documented=sum(item.has_plate_comment for item in results),
        prototype_set=sum(item.has_prototype for item in results),
        return_type_resolved=sum(item.return_type_resolved for item in results),
    )
