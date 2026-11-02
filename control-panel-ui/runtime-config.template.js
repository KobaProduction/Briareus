window.__BRI_CONTROL_PANEL_UI_CONFIG__ = {
  preview: "${CONTROL_PANEL_UI_PREVIEW}".toLowerCase() === "true",
  telemetry: {
    enabled: "${CONTROL_PANEL_UI_TELEMETRY_ENABLED}".toLowerCase() === "true",
    endpoint: "${CONTROL_PANEL_UI_TELEMETRY_ENDPOINT}",
    sampleRate: Number("${CONTROL_PANEL_UI_TELEMETRY_SAMPLE_RATE}") || 1
  },
  events: {
    mode: "${CONTROL_PANEL_UI_EVENTS_MODE}",
    url: "${CONTROL_PANEL_UI_EVENTS_URL}"
  }
}
