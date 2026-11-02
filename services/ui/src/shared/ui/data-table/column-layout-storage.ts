import { recordValue } from "@/shared/lib/transport";

/** Browser-local column keys; table data and permissions are never persisted. */
export interface StoredColumnLayout {
  order: string[];
  hidden: string[];
  shown: string[];
}

function columnKeys(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((key: unknown): key is string => typeof key === "string").slice(0, 100);
}

function decodeLayout(value: unknown): StoredColumnLayout | null {
  const saved = recordValue(value);
  if (!saved || !Array.isArray(saved.order) || !Array.isArray(saved.hidden)) return null;
  return {
    order: columnKeys(saved.order),
    hidden: columnKeys(saved.hidden),
    shown: columnKeys(saved.shown),
  };
}

export function readColumnLayout(key: string): StoredColumnLayout | null {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(`briareus:columns:${key}`) || "null");
    return decodeLayout(saved);
  } catch {
    // Corrupt or disabled browser storage must not break the table.
    return null;
  }
}

export function writeColumnLayout(key: string, layout: StoredColumnLayout): void {
  try {
    localStorage.setItem(`briareus:columns:${key}`, JSON.stringify(layout));
  } catch {
    // The current tab retains its in-memory layout when storage is unavailable.
  }
}
