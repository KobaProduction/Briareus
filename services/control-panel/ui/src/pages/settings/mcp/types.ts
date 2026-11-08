export interface McpCallsSettingsForm {
  logging_enabled: boolean
  logging_capture_payloads: boolean
  logging_retention_days: number
  logging_max_records: number
  maintenance_interval_minutes: number
  mcp_call_timeout_seconds: number
}
