/** Same-origin HTTP mechanics only; features retain authority, DTO and cancellation decisions. */
export interface HttpFailure {
  kind: "unauthorized" | "forbidden" | "conflict" | "invalid" | "unavailable";
  code: string;
}

export function controlPanelHttpFailure(status: number, code: string): HttpFailure {
  return {
    kind:
      status === 401
        ? "unauthorized"
        : status === 403
          ? "forbidden"
          : status === 409
            ? "conflict"
            : status === 422
              ? "invalid"
              : "unavailable",
    code,
  };
}

export function sameOriginJsonRequest(signal: AbortSignal): RequestInit {
  return {
    signal,
    credentials: "same-origin",
    mode: "same-origin",
    redirect: "error",
    referrerPolicy: "no-referrer",
    cache: "no-store",
    headers: { Accept: "application/json" },
  };
}

export function sameOriginJsonCommand(
  signal: AbortSignal,
  operation: string,
  body: string,
): RequestInit {
  return {
    ...sameOriginJsonRequest(signal),
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "Operation-UUID": operation,
      "Idempotency-Key": operation,
    },
    body,
  };
}
