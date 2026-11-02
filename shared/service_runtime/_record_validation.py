"""Typed record validators with separate ORM field binding identities."""

from abc import abstractmethod


class _EventRecordValidation[EventT]:
    @staticmethod
    @abstractmethod
    def _decode_event(value: object, /) -> EventT: ...

    def _event_record(self, _key: str, value: object) -> EventT:
        return self._decode_event(value)


class _AuditRecordValidation[AuditT]:
    @staticmethod
    @abstractmethod
    def _decode_audit(value: object, /) -> AuditT: ...

    def _audit_record(self, _key: str, value: object) -> AuditT:
        return self._decode_audit(value)
