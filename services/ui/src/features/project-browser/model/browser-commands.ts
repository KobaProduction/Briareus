import type {
  BrowserInput,
  BrowserInteraction,
  BrowserInventory,
  BrowserSnapshot,
  BrowserTab,
  BrowserViewport,
} from "@/entities/browser";

export type BrowserPageAction =
  | "local_browser_back"
  | "local_browser_forward"
  | "local_browser_reload";

export interface PendingBrowserOperation {
  operation_id: string;
  tool: string;
}
export interface BrowserReadiness {
  running: boolean;
  pending: PendingBrowserOperation | null;
}

export interface ProjectBrowserClient {
  running(): Promise<boolean>;
  inventory(): Promise<BrowserInventory>;
  open(url: string, pageId: string): Promise<BrowserTab>;
  restore(): Promise<BrowserTab>;
  settings(section: "settings" | "extensions"): Promise<BrowserTab>;
  input(pageId: string, events: BrowserInput[]): Promise<BrowserInteraction>;
  snapshot(pageId: string): Promise<BrowserSnapshot>;
  preview(pageId: string): Promise<string>;
  close(pageId: string): Promise<void>;
  navigate(tool: BrowserPageAction, pageId: string): Promise<void>;
  viewport(pageId: string, width: number, height: number): Promise<BrowserViewport>;
  click(pageId: string, ref: string): Promise<void>;
  fill(pageId: string, ref: string, value: string): Promise<void>;
}

export type BrowserToolCall =
  | { tool: "local_browser_pages" | "local_browser_reopen_closed_page" }
  | { tool: "local_browser_open"; arguments: { url: string; page_id: string } }
  | { tool: "local_browser_settings"; arguments: { section: "settings" | "extensions" } }
  | {
      tool:
        | BrowserPageAction
        | "local_browser_close_page"
        | "local_browser_snapshot"
        | "local_browser_preview";
      arguments: { page_id: string };
    }
  | {
      tool: "local_browser_set_viewport";
      arguments: { page_id: string; width: number; height: number };
    }
  | { tool: "local_browser_click"; arguments: { page_id: string; ref: string } }
  | { tool: "local_browser_fill"; arguments: { page_id: string; ref: string; value: string } }
  | { tool: "local_browser_input"; arguments: { page_id: string; events: BrowserInput[] } };
