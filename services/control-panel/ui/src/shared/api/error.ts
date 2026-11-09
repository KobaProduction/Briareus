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

type TranslateApiError = (key: string, values?: Record<string, string>) => string

export function unavailableServiceMessage(
  code: string,
  service: unknown,
  translate: TranslateApiError,
): string | null {
  if (code !== "service_unavailable") return null
  if (typeof service !== "string" || service.length > 64 || !/^[a-z0-9]+(?:[-_][a-z0-9]+)*$/.test(service)) {
    return translate("apiErrors.serviceUnavailable")
  }
  const names: Record<string, string> = {
    playwright: "Playwright", server: "Server", ghidra: "Ghidra", analysis: "Analyzer R", radare2: "radare2",
    "analysis-g": "Analyzer G", serena: "Serena",
    github: "GitHub", gitlab: "GitLab", signoz: "SigNoz", coolify: "Coolify",
  }
  const label = Object.hasOwn(names, service) ? names[service] : service
  return translate("apiErrors.namedServiceUnavailable", { service: label })
}
