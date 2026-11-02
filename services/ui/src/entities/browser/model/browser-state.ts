export interface BrowserTab {
  page_id: string;
  title: string;
  url: string;
  label?: string;
}
export interface BrowserElement {
  ref: string;
  tag?: string;
  role?: string;
  name?: string;
  text?: string;
  type?: string;
  value?: string;
  disabled?: boolean;
}
export interface BrowserSnapshot {
  page_id: string;
  url: string;
  title: string;
  text: string;
  text_truncated: boolean;
  elements: BrowserElement[];
}
export interface BrowserInventory {
  pages: BrowserTab[];
  canReopen: boolean;
}
export type BrowserInput =
  | {
      kind: "click";
      x: number;
      y: number;
      button: "left" | "middle" | "right";
      click_count: number;
    }
  | { kind: "wheel"; x: number; y: number; delta_x: number; delta_y: number }
  | { kind: "key"; key: string }
  | { kind: "text"; text: string };

export interface BrowserInteraction {
  inventory: BrowserInventory;
  snapshot: BrowserSnapshot;
  preview: string;
}

export interface BrowserViewport {
  width?: number;
  height?: number;
}
export function editableBrowserElement(element: BrowserElement): boolean {
  return (
    element.tag === "textarea" ||
    (element.tag === "input" &&
      !["file", "checkbox", "radio", "submit", "button", "reset", "image", "hidden"].includes(
        (element.type ?? "").toLowerCase(),
      ))
  );
}
export function mergeBrowserInputs(
  previous: BrowserElement[],
  next: BrowserElement[],
  drafts: Record<string, string>,
  samePage: boolean,
): Record<string, string> {
  const result: Record<string, string> = {};
  for (const element of next) {
    if (!editableBrowserElement(element) || (element.type ?? "").toLowerCase() === "password")
      continue;
    const old = previous.find(
      (item) =>
        item.ref === element.ref &&
        item.tag === element.tag &&
        item.type === element.type &&
        item.name === element.name,
    );
    const dirty =
      samePage && old && Object.hasOwn(drafts, element.ref) && drafts[element.ref] !== old.value;
    result[element.ref] = dirty ? (drafts[element.ref] ?? "") : (element.value ?? "");
  }
  return result;
}
export function transportLabel(url: string): string {
  try {
    const protocol = new URL(url).protocol;
    return protocol === "https:"
      ? "HTTPS · шифрованное соединение"
      : protocol === "http:"
        ? "HTTP · без шифрования"
        : "Служебная страница";
  } catch {
    return "Адрес не определён";
  }
}
export function reconcileSelection(tabs: BrowserTab[], selected: string): string {
  return tabs.some((tab) => tab.page_id === selected) ? selected : (tabs[0]?.page_id ?? "");
}
