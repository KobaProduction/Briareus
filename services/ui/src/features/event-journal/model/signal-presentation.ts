import {
  type BusEvent,
  eventProjectId,
  eventTool,
  eventStatus,
  eventDuration,
} from "@/shared/events";
import type { VerifiedPlatformContext } from "@/entities/workspace";

export interface SignalVisibility {
  mode: "events" | "calls";
  metricsEnabled: boolean;
  selectedProjectId: string | null;
  allowSystemEvents: boolean;
  context: VerifiedPlatformContext;
}
export interface SignalRow extends BusEvent {
  id: string;
  projectName: string;
  teamName: string;
  signal: string;
  status: string;
  duration: string;
}
function isMetric(event: BusEvent): boolean {
  return (
    event.topic === "system.metrics" || /^(process|system)\.(snapshot|metrics)/.test(event.type)
  );
}
/** Client visibility follows current verified context; it never grants server
 * access or broadens the independently scoped history subscription. */
export function signalVisible(event: BusEvent, view: SignalVisibility): boolean {
  if (view.mode === "calls" ? event.topic !== "mcp.calls" : event.topic === "mcp.calls")
    return false;
  if (!view.metricsEnabled && isMetric(event)) return false;
  const project = eventProjectId(event);
  if (typeof project !== "string")
    return (
      view.context.user.role === "operator" && !view.selectedProjectId && view.allowSystemEvents
    );
  return view.selectedProjectId
    ? project === view.selectedProjectId
    : view.context.projects.some((item) => item.id === project);
}
export function presentSignal(event: BusEvent, context: VerifiedPlatformContext): SignalRow {
  const project = context.projects.find((item) => item.id === eventProjectId(event));
  const duration = eventDuration(event);
  const teamName = project
    ? project.owner.kind === "user"
      ? "Личные проекты"
      : context.teams.find((team) => team.id === project.owner.id)?.name || "Команда"
    : "Система";
  return {
    ...event,
    id: event.id ?? event.occurredAt + event.topic + event.type,
    projectName: project?.name || "Система",
    teamName,
    signal: eventTool(event) ?? event.type,
    status: eventStatus(event) ?? "событие",
    duration: duration !== null ? `${duration} мс` : "—",
  };
}
export function signalTopics(mode: "events" | "calls", metricsEnabled: boolean): string[] {
  if (mode === "calls") return ["mcp.calls"];
  return [
    "management.events",
    "browser.runtime",
    "system.notifications",
    "platform.context",
    "access.sessions",
    ...(metricsEnabled ? ["system.metrics"] : []),
  ];
}
