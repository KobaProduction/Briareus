import type { BrowserTabPolicy } from "./control-panel"

export interface BrowserPage {
  page_id: string
  label?: string
  title?: string
  url?: string
  page_agent_access?: boolean
}
export interface BrowserOperatorState {
  tab_policy?: BrowserTabPolicy
  selected_page_id?: string
  pages?: BrowserPage[]
  agent_access_enabled?: boolean
  developer_access_enabled?: boolean
  developer_access_effective?: boolean
  can_reopen_closed_tab?: boolean
  capabilities?: Record<string, boolean> | string[]
  viewport?: { width?: number; height?: number }
  color_scheme?: "system" | "light" | "dark"
}
export interface BrowserClipboardMessage {
  type: "clipboard"
  request_id: string
  page_id: string
  text: string
}
export type BrowserOperatorMessage =
  | ({ type: "state" } & BrowserOperatorState)
  | BrowserClipboardMessage
  | { type: "frame"; page_id: string; data: string; metadata?: { deviceWidth?: number; deviceHeight?: number } }
  | { type: "navigation_complete"; request_id: string; page_id: string; url: string }
  | { type: "error"; request_id?: string; code?: string; message?: string; max_tabs?: number }

export type BrowserOperatorCommand =
  | { type: "refresh_state" | "close_all_pages" | "reopen_closed_page" | "clean_app" | "clean_browser" | "back" | "reload" }
  | { type: "navigate"; url: string; request_id: string }
  | { type: "new_page"; url?: string }
  | { type: "select_page" | "close_page"; page_id: string }
  | { type: "set_developer_access" | "set_agent_access"; allowed: boolean }
  | { type: "clipboard_read"; page_id: string; request_id: string }
  | { type: "text"; page_id: string; text: string }
  | { type: "key"; page_id: string; key: string }
  | { type: "mouse"; page_id: string; event: string; x: number; y: number; button?: string; click_count?: number; delta_x?: number; delta_y?: number }
