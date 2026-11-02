import type { BusEvent } from "./event-data";

export function eventProjectId(event: BusEvent): string | null | undefined {
  const data = event.data;
  return data && "project_id" in data ? data.project_id : undefined;
}
export function eventTool(event: BusEvent): string | null {
  const data = event.data;
  return data && "tool" in data ? data.tool : null;
}
export function eventStatus(event: BusEvent): string | null {
  const data = event.data;
  return data && "status" in data ? data.status : null;
}
export function eventDuration(event: BusEvent): number | null {
  const data = event.data;
  return data && "duration_ms" in data ? data.duration_ms : null;
}
