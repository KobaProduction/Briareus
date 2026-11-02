"""Decode authenticated owner-ledger results using each source operation's existing receipt."""

import json
from collections.abc import Mapping

from pydantic import BaseModel

from common.owner_contracts import OwnerAuthorityUnavailable
from projects.application.owner_receipts import (
    CatalogListMetadataCommitted,
    CatalogResolveMetadataCommitted,
    FilesConfigureQuota,
    FilesListFileIndex,
    FilesMarkDispatched,
    FilesMarkUnknown,
    FilesMetadataAsCommittedRead,
    FilesReconcileWrite,
    FilesReleaseUndispatched,
    FilesReserveWrite,
    ReverseCancelBeforeDispatch,
    ReverseMarkDispatched,
    ReverseMarkUnknown,
    ReverseReconcileImport,
    ReverseReserveImport,
    RuntimeCancelUndispatchedJob,
    RuntimeConfirmCleanup,
    RuntimeDispatchJob,
    RuntimeMarkJobUnknown,
    RuntimeOpenRuntime,
    RuntimeQueueJob,
    RuntimeReconcileNativeJob,
    RuntimeRenewRuntime,
    RuntimeRevokeRuntime,
)

type FilesEffectResult = (
    FilesConfigureQuota
    | FilesListFileIndex
    | FilesMarkDispatched
    | FilesMarkUnknown
    | FilesMetadataAsCommittedRead
    | FilesReconcileWrite
    | FilesReleaseUndispatched
    | FilesReserveWrite
)


_FILES_RESULTS: dict[str, type[FilesEffectResult]] = {
    "files.quota.configure": FilesConfigureQuota,
    "files.list": FilesListFileIndex,
    "files.write.dispatch": FilesMarkDispatched,
    "files.write.mark_unknown": FilesMarkUnknown,
    "files.metadata": FilesMetadataAsCommittedRead,
    "files.write.reconcile": FilesReconcileWrite,
    "files.write.finalize": FilesReconcileWrite,
    "files.write.release": FilesReleaseUndispatched,
    "files.write.reserve": FilesReserveWrite,
}


type RuntimeEffectResult = (
    RuntimeCancelUndispatchedJob
    | RuntimeConfirmCleanup
    | RuntimeDispatchJob
    | RuntimeMarkJobUnknown
    | RuntimeOpenRuntime
    | RuntimeQueueJob
    | RuntimeReconcileNativeJob
    | RuntimeRenewRuntime
    | RuntimeRevokeRuntime
)


_RUNTIME_RESULTS: dict[str, type[RuntimeEffectResult]] = {
    "runtime.job.cancel": RuntimeCancelUndispatchedJob,
    "runtime.cleanup.confirm": RuntimeConfirmCleanup,
    "runtime.job.mark_unknown": RuntimeMarkJobUnknown,
    "runtime.session.open": RuntimeOpenRuntime,
    "runtime.job.reconcile": RuntimeReconcileNativeJob,
    "runtime.session.renew": RuntimeRenewRuntime,
    "runtime.session.revoke": RuntimeRevokeRuntime,
    "runtime.terminal.job.queue": RuntimeQueueJob,
    "runtime.terminal.job.dispatch": RuntimeDispatchJob,
    "runtime.web.job.queue": RuntimeQueueJob,
    "runtime.web.job.dispatch": RuntimeDispatchJob,
    "runtime.reverse.job.queue": RuntimeQueueJob,
    "runtime.reverse.job.dispatch": RuntimeDispatchJob,
}


type ReverseEffectResult = (
    ReverseCancelBeforeDispatch
    | ReverseMarkDispatched
    | ReverseMarkUnknown
    | ReverseReconcileImport
    | ReverseReserveImport
)


_REVERSE_RESULTS: dict[str, type[ReverseEffectResult]] = {
    "reverse.import.cancel": ReverseCancelBeforeDispatch,
    "reverse.import.dispatch": ReverseMarkDispatched,
    "reverse.import.mark_unknown": ReverseMarkUnknown,
    "reverse.import.reconcile": ReverseReconcileImport,
    "reverse.import.reserve": ReverseReserveImport,
    "reverse.import.claim": ReverseReserveImport,
}


type CatalogEffectResult = CatalogListMetadataCommitted | CatalogResolveMetadataCommitted


_CATALOG_RESULTS: dict[str, type[CatalogEffectResult]] = {
    "catalog.integrations.list": CatalogListMetadataCommitted,
    "catalog.variables.list": CatalogListMetadataCommitted,
    "catalog.integrations.resolve": CatalogResolveMetadataCommitted,
    "catalog.variables.resolve": CatalogResolveMetadataCommitted,
}


def _decode[ResultT: BaseModel](
    operation: str, value: bytes, models: Mapping[str, type[ResultT]]
) -> ResultT:
    model = models.get(operation)
    if model is None:
        raise OwnerAuthorityUnavailable("owner result operation has no source receipt")
    try:
        result = model.model_validate_json(value, strict=True)
        document: object = json.loads(value)
        if not isinstance(document, dict) or document != result.model_dump(mode="json"):
            raise ValueError("owner result differs from its complete receipt schema")
        return result
    except (ValueError, TypeError):
        raise OwnerAuthorityUnavailable("authenticated owner result schema invalid") from None


def decode_files_result(operation: str, value: bytes) -> FilesEffectResult:
    return _decode(operation, value, _FILES_RESULTS)


def files_result_status(result: FilesEffectResult) -> str | None:
    if isinstance(result, FilesConfigureQuota):
        return None
    return result.status


def decode_runtime_result(operation: str, value: bytes) -> RuntimeEffectResult:
    return _decode(operation, value, _RUNTIME_RESULTS)


def runtime_result_status(result: RuntimeEffectResult) -> str | None:
    if isinstance(result, (RuntimeOpenRuntime, RuntimeRenewRuntime)):
        return None
    return result.status


def decode_reverse_result(operation: str, value: bytes) -> ReverseEffectResult:
    return _decode(operation, value, _REVERSE_RESULTS)


def reverse_result_status(result: ReverseEffectResult) -> str | None:
    return result.status


def decode_catalog_result(operation: str, value: bytes) -> CatalogEffectResult:
    return _decode(operation, value, _CATALOG_RESULTS)


def catalog_result_status(result: CatalogEffectResult) -> str | None:
    return result.status
