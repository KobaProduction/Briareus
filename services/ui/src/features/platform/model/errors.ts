/** Presentation-level error categories, independent of still-unapproved C1-B routes. */
export type UiErrorKind =
  | "conflict"
  | "unauthorized"
  | "forbidden"
  | "unavailable"
  | "invalid"
  | "uncertain"
  | "unknown";
export interface UiError {
  kind: UiErrorKind;
  message: string;
  code: string;
}

/** B18: No global A9 `DraftContractError` remains after the dead client
 * was deleted. Only the real local pre-send BFF capability guard can deny a
 * command without risking a previously committed remote side effect. */
/** Only known error codes may enter reactive UI state; never raw exception
 * text, arbitrary server-selected values, payloads, secrets or full URLs. */
const errorCodes = new Set([
  "contract_not_available",
  "invalid_invitation",
  "last_superuser",
  "resource_ambiguous",
  "operation_in_progress",
  "idempotency_key_conflict",
]);
type TransportFailureKind = "network" | "aborted" | null;
interface ErrorEnvelope {
  status: number | null;
  code: string;
  kind: TransportFailureKind;
}
function errorStatus(value: unknown): number | null {
  return value !== null &&
    typeof value === "object" &&
    "status" in value &&
    typeof value.status === "number"
    ? value.status
    : null;
}
function errorCodeCandidate(value: unknown): string | null {
  return value !== null &&
    typeof value === "object" &&
    "code" in value &&
    typeof value.code === "string"
    ? value.code
    : null;
}
function transportFailureKind(value: unknown): TransportFailureKind {
  if (
    value !== null &&
    typeof value === "object" &&
    "kind" in value &&
    (value.kind === "network" || value.kind === "aborted")
  )
    return value.kind;
  return null;
}
function errorEnvelope(error: unknown): ErrorEnvelope {
  const envelope =
    error !== null && typeof error === "object" && "error" in error ? error.error : null;
  const status = errorStatus(error) ?? errorStatus(envelope);
  const candidate = errorCodeCandidate(error) ?? errorCodeCandidate(envelope) ?? "";
  // Allow only a short identifier; never retain a raw URL, stack, token,
  // response body, user/project ID or attacker-supplied free-form error.
  const code = errorCodes.has(candidate) ? candidate : "";
  return { status, code, kind: transportFailureKind(error) };
}
const statusErrors: Partial<Record<number, Pick<UiError, "kind" | "message">>> = {
  401: { kind: "unauthorized", message: "authenticationExpired" },
  503: { kind: "unavailable", message: "serviceUnavailableOrUpgrading" },
  429: { kind: "unavailable", message: "rateLimited" },
  403: { kind: "forbidden", message: "permissionDenied" },
  404: { kind: "invalid", message: "recordMissing" },
  400: { kind: "invalid", message: "invalidInput" },
  422: { kind: "invalid", message: "invalidInput" },
};
const conflictMessages: Record<string, string> = {
  last_superuser: "lastSuperuser",
  resource_ambiguous: "resourceAmbiguous",
  operation_in_progress: "operationInProgress",
  idempotency_key_conflict: "idempotencyConflict",
};
function codedError(status: number | null, code: string): UiError | null {
  if (code === "contract_not_available" && [null, 404, 501].includes(status)) {
    return { kind: "unavailable", code, message: "contractPending" };
  }
  if (code === "invalid_invitation" && (status === 400 || status === 422)) {
    return { kind: "invalid", code, message: "invitationInvalid" };
  }
  if (status === 409)
    return { kind: "conflict", code, message: conflictMessages[code] ?? "conflict" };
  return null;
}
function transportError(error: unknown, envelope: ErrorEnvelope): UiError {
  const { status, code, kind } = envelope;
  if (status === 408 || (status !== null && status >= 500)) {
    return { kind: "unavailable", code, message: "unavailable" };
  }
  if (kind === "network" || error instanceof TypeError) {
    return { kind: "unavailable", code, message: "unavailable" };
  }
  if (kind === "aborted" || (error instanceof DOMException && error.name === "AbortError")) {
    return { kind: "unavailable", code, message: "requestCancelled" };
  }
  return { kind: "unknown", code, message: "unknownError" };
}
export function normalizeUiError(error: unknown, phase: "read" | "mutation" = "read"): UiError {
  const envelope = errorEnvelope(error);
  const { status, code } = envelope;
  // After an outbound write, 400/401/403/404/409/422/503 and network loss
  // are all POSSIBLY post-commit. Only the ORIGINAL signed BFF owner status
  // plus a current affected-domain read may resolve the retry fence.
  if (phase === "mutation") return { kind: "uncertain", code, message: "outcomeUncertain" };
  // HTTP authorization and throttling outcomes take precedence over a
  // free-form transport error code. In particular a forged/stale
  // `contract_not_available` MUST NOT turn an authenticated 401 into an
  // offline state that retains the previous User context.
  if (status === 401 || status === 403 || status === 429 || status === 503) {
    const issue = statusErrors[status];
    if (issue) return { ...issue, code: status === 503 ? "service_unavailable" : code };
  }
  // A future Authorization-owned schema migration may temporarily keep
  // verified Admin callers unavailable. 503 is NOT evidence migrations ran;
  // never trigger a client-side migration, fake readiness or replay a write.
  const coded = codedError(status, code);
  if (coded) return coded;
  const issue = status === null ? undefined : statusErrors[status];
  return issue ? { ...issue, code } : transportError(error, envelope);
}
