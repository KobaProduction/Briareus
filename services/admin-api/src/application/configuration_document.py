"""Strict cache document mapping; configuration invariants belong to the domain."""

from typing import Self

from domain.configuration import AdminConfig

from common.models import StrictModel

_DEFAULT = AdminConfig()


class AdminConfigDocument(StrictModel):
    logging_enabled: bool = _DEFAULT.logging_enabled
    logging_capture_payloads: bool = _DEFAULT.logging_capture_payloads
    logging_retention_days: int = _DEFAULT.logging_retention_days
    logging_max_records: int = _DEFAULT.logging_max_records
    maintenance_interval_minutes: int = _DEFAULT.maintenance_interval_minutes

    def record(self) -> AdminConfig:
        return AdminConfig(
            logging_enabled=self.logging_enabled,
            logging_capture_payloads=self.logging_capture_payloads,
            logging_retention_days=self.logging_retention_days,
            logging_max_records=self.logging_max_records,
            maintenance_interval_minutes=self.maintenance_interval_minutes,
        )

    @classmethod
    def from_record(cls, value: AdminConfig) -> Self:
        return cls(
            logging_enabled=value.logging_enabled,
            logging_capture_payloads=value.logging_capture_payloads,
            logging_retention_days=value.logging_retention_days,
            logging_max_records=value.logging_max_records,
            maintenance_interval_minutes=value.maintenance_interval_minutes,
        )
