import { recordValue, requireRecord } from "@/shared/lib/transport";
import type {
  BrowserElement,
  BrowserInteraction,
  BrowserInventory,
  BrowserSnapshot,
  BrowserTab,
  BrowserViewport,
} from "./browser-state";
export function browserTab(value: unknown): BrowserTab {
  const row = requireRecord(value);
  if (typeof row.page_id !== "string" || typeof row.url !== "string")
    throw new Error("BROWSER_PAGE_INVALID");
  return {
    page_id: row.page_id,
    url: row.url,
    title: typeof row.title === "string" ? row.title : "",
    label: typeof row.label === "string" ? row.label : undefined,
  };
}
export function browserInventory(value: unknown): BrowserInventory {
  const row = requireRecord(value);
  if (!Array.isArray(row.pages)) throw new Error("BROWSER_PAGES_INVALID");
  return { pages: row.pages.map(browserTab), canReopen: row.can_reopen_closed_tab === true };
}
function browserElement(value: unknown): BrowserElement {
  const row = requireRecord(value);
  if (typeof row.ref !== "string") throw new Error("BROWSER_ELEMENT_INVALID");
  const result: BrowserElement = { ref: row.ref };
  for (const key of ["tag", "role", "name", "text", "type", "value"] as const) {
    if (typeof row[key] === "string") result[key] = row[key];
  }
  if (typeof row.disabled === "boolean") result.disabled = row.disabled;
  return result;
}
export function browserSnapshot(value: unknown): BrowserSnapshot {
  const row = requireRecord(value),
    tab = browserTab(value);
  if (row.elements !== undefined && !Array.isArray(row.elements))
    throw new Error("BROWSER_ELEMENTS_INVALID");
  return {
    ...tab,
    text: typeof row.text === "string" ? row.text : "",
    text_truncated: row.text_truncated === true,
    elements: Array.isArray(row.elements) ? row.elements.map(browserElement) : [],
  };
}
export function browserPreview(value: unknown, pageId: string): string {
  const row = requireRecord(value);
  if (
    row.page_id !== pageId ||
    row.mime_type !== "image/png" ||
    typeof row.data_base64 !== "string"
  )
    return "";
  return row.data_base64.length <= 1400000 && /^[A-Za-z0-9+/]+=*$/.test(row.data_base64)
    ? `data:image/png;base64,${row.data_base64}`
    : "";
}

export function browserInteraction(value: unknown, pageId: string): BrowserInteraction {
  const row = requireRecord(value);
  const snapshot = browserSnapshot(row.snapshot);
  if (snapshot.page_id !== pageId) throw new Error("BROWSER_INTERACTION_INVALID");
  return {
    inventory: browserInventory(row.inventory),
    snapshot,
    preview: browserPreview(row.preview, pageId),
  };
}
export function browserViewport(value: unknown): BrowserViewport {
  const viewport = recordValue(requireRecord(value).viewport);
  return {
    width: typeof viewport?.width === "number" ? viewport.width : undefined,
    height: typeof viewport?.height === "number" ? viewport.height : undefined,
  };
}
