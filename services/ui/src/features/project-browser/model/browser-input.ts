import type { BrowserInput } from "@/entities/browser";

export interface BrowserSurface {
  left: number;
  top: number;
  width: number;
  height: number;
  naturalWidth: number;
  naturalHeight: number;
}

export function browserPoint(
  x: number,
  y: number,
  surface: BrowserSurface,
): { x: number; y: number } | null {
  if (
    surface.width <= 0 ||
    surface.height <= 0 ||
    surface.naturalWidth <= 0 ||
    surface.naturalHeight <= 0
  )
    return null;
  const point = { x: x - surface.left, y: y - surface.top };
  if (point.x < 0 || point.y < 0 || point.x >= surface.width || point.y >= surface.height)
    return null;
  return {
    x: Math.min(
      surface.naturalWidth - 1,
      Math.round((point.x * surface.naturalWidth) / surface.width),
    ),
    y: Math.min(
      surface.naturalHeight - 1,
      Math.round((point.y * surface.naturalHeight) / surface.height),
    ),
  };
}

export function browserKey(
  event: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey"> & {
    isComposing?: boolean;
  },
): BrowserInput | null {
  if (event.isComposing || (event.shiftKey && event.key === "Insert")) return null;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v") return null;
  if (["Control", "Meta", "Alt", "Shift", "Dead", "Process", "Unidentified"].includes(event.key))
    return null;
  if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey)
    return { kind: "text", text: event.key };
  const modifiers = [
    event.ctrlKey && "Control",
    event.metaKey && "Meta",
    event.altKey && "Alt",
    event.shiftKey && "Shift",
  ];
  return { kind: "key", key: [...modifiers.filter(Boolean), event.key].join("+") };
}

export function browserTextInputs(text: string): BrowserInput[] | null {
  if (text.length > 65536) return null;
  const events: BrowserInput[] = [];
  let chunk = "";
  for (const character of text) {
    if (chunk.length + character.length > 1024) {
      events.push({ kind: "text", text: chunk });
      chunk = "";
    }
    chunk += character;
  }
  if (chunk) events.push({ kind: "text", text: chunk });
  return events;
}

export function appendBrowserInput(events: BrowserInput[], input: BrowserInput): void {
  const previous = events.at(-1);
  if (
    previous?.kind === "text" &&
    input.kind === "text" &&
    previous.text.length + input.text.length <= 1024
  )
    previous.text += input.text;
  else if (previous?.kind === "wheel" && input.kind === "wheel") {
    previous.delta_x = Math.max(-10000, Math.min(10000, previous.delta_x + input.delta_x));
    previous.delta_y = Math.max(-10000, Math.min(10000, previous.delta_y + input.delta_y));
  } else events.push(input);
}
