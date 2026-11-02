from __future__ import annotations

from dataclasses import dataclass


def require_logging_flag(value: object) -> None:
    if type(value) is not bool:
        raise ValueError("Boolean logging settings required")


@dataclass(frozen=True, slots=True, kw_only=True)
class AdminConfig:
    logging_enabled: bool = True
    logging_capture_payloads: bool = True
    logging_retention_days: int = 30
    logging_max_records: int = 10_000
    maintenance_interval_minutes: int = 60

    def __post_init__(self) -> None:
        require_logging_flag(self.logging_enabled)
        require_logging_flag(self.logging_capture_payloads)
        for name, value, lower, upper in (
            ("logging_retention_days", self.logging_retention_days, 1, 3650),
            ("logging_max_records", self.logging_max_records, 100, 1_000_000),
            ("maintenance_interval_minutes", self.maintenance_interval_minutes, 1, 1440),
        ):
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{name} must be an integer between {lower} and {upper}")
