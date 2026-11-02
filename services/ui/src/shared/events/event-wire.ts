import { requireRecord } from "../lib/transport";
import { contextSnapshot } from "./context-wire";
import type {
  ActorOperation,
  BrowserOperationData,
  BusEvent,
  CallFacts,
  CallStatus,
  EventData,
  GatewayCallData,
  McpOwnerPublicationData,
  OwnerPublicationData,
  OwnerSource,
} from "./event-data";
import { literal, nullableText, numeric, optionalText, text } from "./wire-values";

function callStatus(value: unknown): CallStatus {
  switch (value) {
    case "started":
    case "unknown":
    case "denied":
    case "failed":
    case "completed":
      return value;
    default:
      throw Error("Invalid call status");
  }
}
function ownerSource(value: unknown): OwnerSource {
  if (value !== "platform" && value !== "access" && value !== "resources")
    throw Error("Invalid event owner");
  return value;
}
function actorOperation(row: Record<string, unknown>): ActorOperation {
  return { actor_id: text(row, "actor_id"), operation_id: text(row, "operation_id") };
}
function callFacts(row: Record<string, unknown>): CallFacts {
  return {
    hand: text(row, "hand"),
    tool: text(row, "tool"),
    status: callStatus(row.status),
    duration_ms: numeric(row, "duration_ms"),
  };
}
function gatewayCall(value: unknown): GatewayCallData {
  const row = requireRecord(value);
  const facts = callFacts(row);
  if (facts.status !== "completed" && facts.status !== "failed" && facts.status !== "unknown") {
    throw Error("Invalid gateway call status");
  }
  if (
    !Number.isInteger(facts.duration_ms) ||
    facts.duration_ms < 0 ||
    facts.duration_ms > 86_400_000
  ) {
    throw Error("Invalid gateway call duration");
  }
  return {
    ...facts,
    hand: gatewayHand(facts.hand),
    status: facts.status,
    session_uuid: nullableText(row, "session_uuid"),
    node_uuid: text(row, "node_uuid"),
    placement_uuid: text(row, "placement_uuid"),
    transport: literal(row, "transport", "gateway-mcp"),
  };
}
function gatewayHand(value: string): GatewayCallData["hand"] {
  switch (value) {
    case "files":
    case "terminal":
    case "web":
    case "svc":
    case "reverse":
    case "infrastructure":
    case "serena":
      return value;
    default:
      throw Error("Invalid MCP hand");
  }
}
function ownerPublication(row: Record<string, unknown>): OwnerPublicationData {
  return {
    event_id: text(row, "event_id"),
    type: text(row, "type"),
    occurredAt: text(row, "occurredAt"),
    actor_id: nullableText(row, "actor_id"),
    project_id: nullableText(row, "project_id"),
    operation_id: nullableText(row, "operation_id"),
    entity_id: nullableText(row, "entity_id"),
    source: ownerSource(row.source),
  };
}
function ownerChange(row: Record<string, unknown>): OwnerPublicationData | McpOwnerPublicationData {
  const owner = ownerPublication(row);
  if (row.call === undefined) return owner;
  const call = gatewayCall(row.call),
    flat = gatewayCall(row);
  const fields: readonly (keyof GatewayCallData)[] = [
    "hand",
    "tool",
    "status",
    "duration_ms",
    "session_uuid",
    "node_uuid",
    "placement_uuid",
    "transport",
  ];
  if (fields.some((key) => call[key] !== flat[key])) {
    throw Error("Conflicting MCP call projections");
  }
  return { ...owner, ...flat, call };
}
function managementData(eventType: string, row: Record<string, unknown>): EventData {
  if (eventType.startsWith("node."))
    return { node_id: nullableText(row, "node_id"), actor_id: text(row, "actor_id") };
  if (eventType.startsWith("connection."))
    return {
      connection_id: nullableText(row, "connection_id"),
      project_id: text(row, "project_id"),
      actor_id: text(row, "actor_id"),
    };
  if (eventType.startsWith("session."))
    return { ...actorOperation(row), project_id: text(row, "project_id") };
  return { ...actorOperation(row), action: text(row, "action") };
}
function notificationData(eventType: string, row: Record<string, unknown>): EventData {
  if (eventType === "resync.required") return { reason: optionalText(row, "reason") };
  if (eventType.startsWith("source."))
    return { source: ownerSource(row.source), project_id: nullableText(row, "project_id") };
  return { project_id: text(row, "project_id"), action: text(row, "action") };
}
export function decodeEventData(topic: string, eventType: string, value: unknown): EventData {
  const row = requireRecord(value);
  if (typeof row.event_id === "string" && row.source !== undefined) return ownerChange(row);
  switch (topic) {
    case "platform.context":
      return contextSnapshot(row);
    case "system.metrics":
      return {
        source: literal(row, "source", "control-panel-api"),
        uptime_seconds: numeric(row, "uptime_seconds"),
        cpu_user_seconds: numeric(row, "cpu_user_seconds"),
        cpu_system_seconds: numeric(row, "cpu_system_seconds"),
        peak_memory_kib: numeric(row, "peak_memory_kib"),
      };
    case "mcp.calls":
      return {
        ...callFacts(row),
        ...actorOperation(row),
        project_id: text(row, "project_id"),
        transport: literal(row, "transport", "panel-owner-rpc"),
      };
    case "browser.runtime":
      return browserOperation(row);
    case "management.events":
      return managementData(eventType, row);
    case "system.notifications":
      return notificationData(eventType, row);
    default:
      throw Error("Unknown event contract");
  }
}
function browserOperation(row: Record<string, unknown>): BrowserOperationData {
  return {
    project_id: text(row, "project_id"),
    operation_id: text(row, "operation_id"),
    tool: text(row, "tool"),
    status: callStatus(row.status),
  };
}
/** History and live delivery share exactly the same typed event decoder. */
export function decodeJournalEvent(value: unknown): BusEvent {
  const row = requireRecord(value),
    topic = text(row, "topic"),
    eventType = text(row, "type");
  const identifier = row.event_id;
  if (identifier !== undefined && identifier !== null && typeof identifier !== "string")
    throw Error("Invalid event id");
  return {
    id: typeof identifier === "string" ? identifier : undefined,
    topic,
    type: eventType,
    occurredAt: text(row, "occurredAt"),
    data: decodeEventData(topic, eventType, row.data),
  };
}
