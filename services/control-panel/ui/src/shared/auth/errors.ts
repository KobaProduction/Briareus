import { ControlPanelApiError } from "../api/error"

export type IdentityErrorCode = "accessDenied" | "loginRequired" | "interactionRequired" | "providerUnavailable" | "configuration" | "callback"

export class IdentityError extends Error {
  constructor(readonly code: IdentityErrorCode, cause?: unknown) {
    super(`Identity failure: ${code}`, { cause })
    this.name = "IdentityError"
  }
}

export class IdentityCallbackError extends IdentityError {
  constructor(cause: unknown) {
    super(callbackCode(cause), cause)
    this.name = "IdentityCallbackError"
  }
}

function callbackCode(cause: unknown): IdentityErrorCode {
  const code = cause && typeof cause === "object" && "error" in cause ? cause.error : null
  switch (code) {
    case "access_denied": return "accessDenied"
    case "login_required": return "loginRequired"
    case "interaction_required":
    case "consent_required":
    case "account_selection_required": return "interactionRequired"
    case "server_error":
    case "temporarily_unavailable": return "providerUnavailable"
    default: return "callback"
  }
}

export interface PanelFailure {
  messageKey: string
  retry: boolean
  requestId: string
}

export function panelFailure(error: unknown): PanelFailure {
  if (error instanceof IdentityError) return { messageKey: `authErrors.${error.code}`, retry: false, requestId: "" }
  if (error instanceof ControlPanelApiError) {
    const requestId = /^[A-Za-z0-9_.:-]{1,128}$/.test(error.requestId) ? error.requestId : ""
    if (error.status === 401) return { messageKey: "authErrors.loginRequired", retry: false, requestId }
    if (error.status === 403) return { messageKey: error.code === "access_denied" ? "authErrors.projectAccessDenied" : "authErrors.forbidden", retry: false, requestId }
    if (error.code === "service_unavailable") return { messageKey: "apiErrors.serviceUnavailable", retry: true, requestId }
    if (error.kind === "network") return { messageKey: "authErrors.network", retry: true, requestId }
    return { messageKey: "authErrors.panelUnavailable", retry: true, requestId }
  }
  return { messageKey: "authErrors.unexpected", retry: true, requestId: "" }
}
