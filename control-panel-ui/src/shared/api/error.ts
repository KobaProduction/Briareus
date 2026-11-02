export type ControlPanelApiErrorKind = "http" | "network" | "aborted"

export class ControlPanelApiError extends Error {
  constructor(
    message: string,
    readonly kind: ControlPanelApiErrorKind,
    readonly status: number | null = null,
    readonly code: string = "",
    readonly requestId: string = "",
    options: ErrorOptions = {},
  ) {
    super(message, options)
    this.name = "ControlPanelApiError"
  }
}
