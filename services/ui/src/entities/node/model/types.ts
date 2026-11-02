export interface ResourceLimits {
  memory_bytes: number;
  cpu_millis: number;
  pids: number;
}
export interface ManagedNode {
  id: string;
  name: string;
  scope: "personal" | "team" | "shared";
  owner_uuid: string | null;
  host_uuid: string;
  runtime_uid: number;
  endpoint: string;
  budget: { total: ResourceLimits; reserved: ResourceLimits };
  enabled: boolean;
  paired: boolean;
  sequence: number;
  last_seen_at: string | null;
  created_at: string;
}
