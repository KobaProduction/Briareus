import { type BusEvent, eventProjectId, eventTool } from "@/shared/events";

/** Local commands refresh their own result; their audit must not trigger another read. */
export function browserRefreshRequired(
  event: BusEvent,
  projectId: string | null,
  ownRequests: ReadonlySet<string>,
): boolean {
  const project = eventProjectId(event);
  if (project && project !== projectId) return false;
  if (eventTool(event) === "local_browser_status") return false;
  const data = event.data;
  return !(
    data &&
    "operation_id" in data &&
    data.operation_id &&
    ownRequests.has(data.operation_id)
  );
}
