import type { ContextSnapshotData } from "../api";

/** Deployed Panel event facts. These wire projections never grant authority. */
export type OwnerSource = "platform" | "access" | "resources";
export type CallStatus = "started" | "unknown" | "denied" | "failed" | "completed";

export interface ProcessMetricsData {
  source: "control-panel-api";
  uptime_seconds: number;
  cpu_user_seconds: number;
  cpu_system_seconds: number;
  peak_memory_kib: number;
}
export interface CallFacts {
  hand: string;
  tool: string;
  status: CallStatus;
  duration_ms: number;
}
export interface ActorOperation {
  actor_id: string;
  operation_id: string;
}
export interface PanelCallData extends CallFacts, ActorOperation {
  project_id: string;
  transport: "panel-owner-rpc";
}
export interface GatewayCallData extends CallFacts {
  hand: "files" | "terminal" | "web" | "svc" | "reverse" | "infrastructure" | "serena";
  status: "completed" | "failed" | "unknown";
  session_uuid: string | null;
  node_uuid: string;
  placement_uuid: string;
  transport: "gateway-mcp";
}
export interface BrowserOperationData {
  project_id: string;
  operation_id: string;
  tool: string;
  status: CallStatus;
}
export interface PlatformMutationData extends ActorOperation {
  action: string;
}
export interface AccessMutationData extends ActorOperation {
  project_id: string;
}
export interface AccessNotificationData {
  project_id: string;
  action: string;
}
export interface ConnectionMutationData {
  project_id: string;
  connection_id: string | null;
  actor_id: string;
}
export interface NodeMutationData {
  node_id: string | null;
  actor_id: string;
}
export interface OwnerPublicationData {
  event_id: string;
  type: string;
  occurredAt: string;
  actor_id: string | null;
  project_id: string | null;
  operation_id: string | null;
  entity_id: string | null;
  source: OwnerSource;
}
export interface McpOwnerPublicationData extends OwnerPublicationData, GatewayCallData {
  call: GatewayCallData;
}
export interface ResyncData {
  reason?: string | null;
}
export interface SourceNoticeData {
  source: OwnerSource;
  project_id: string | null;
}

export type EventData =
  | ProcessMetricsData
  | PanelCallData
  | BrowserOperationData
  | PlatformMutationData
  | AccessMutationData
  | AccessNotificationData
  | ConnectionMutationData
  | NodeMutationData
  | OwnerPublicationData
  | McpOwnerPublicationData
  | ResyncData
  | SourceNoticeData
  | ContextSnapshotData;

export interface BusEvent {
  id?: string;
  topic: string;
  type: string;
  occurredAt: string;
  data: EventData | null;
}
