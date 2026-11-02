export type EventTransportMode = "mock" | "websocket" | "hybrid"
export interface ControlPanelUiRuntimeConfig {
  preview: boolean
  telemetry: { enabled: boolean; endpoint: string; sampleRate: number }
  events: { mode: EventTransportMode; url: string }
}
declare global { interface Window { __BRI_CONTROL_PANEL_UI_CONFIG__?: Partial<ControlPanelUiRuntimeConfig> & { telemetry?: Partial<ControlPanelUiRuntimeConfig["telemetry"]>; events?: Partial<ControlPanelUiRuntimeConfig["events"]> } } }
const raw=window.__BRI_CONTROL_PANEL_UI_CONFIG__
export const runtimeConfig: ControlPanelUiRuntimeConfig={
  preview: raw?.preview ?? false,
  telemetry:{ enabled:raw?.telemetry?.enabled ?? true, endpoint:raw?.telemetry?.endpoint ?? "/api/telemetry", sampleRate:raw?.telemetry?.sampleRate ?? 1 },
  events:{ mode:raw?.events?.mode ?? "hybrid", url:raw?.events?.url ?? "/api/realtime" },
}
