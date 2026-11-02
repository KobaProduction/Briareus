import type { RuntimePolicyKey, RuntimePolicyValues } from "./node-commands";
import type { ManagedNode, ResourceLimits } from "@/entities/node";
export interface NodeSetup {
  node_record: {
    id: string;
    name: string;
    scope: { kind: ManagedNode["scope"]; owner_uuid: string | null };
    budget: ManagedNode["budget"];
    enabled: boolean;
    shared_use: boolean;
    shared_manage: boolean;
    created_at: string;
  };
  core_verify_key: string;
  gateway_verify_key: string;
  runtime_uid: number;
  runtime_user: string;
  runtime_gid: number;
  rootless_budget: ResourceLimits;
  endpoint: string;
  origin_approved: boolean;
  journal: { target: string; ca_certificate: string };
}
export interface NodeRuntimePolicy {
  scope: "server" | "node";
  node_uuid: string | null;
  sequence: number;
  overrides: RuntimePolicyValues;
  effective: Record<RuntimePolicyKey, number | null>;
  sources: Record<RuntimePolicyKey, "default" | "server" | "node">;
  applies_on: "placement_update";
}
export type NodeReplyDecoder<T> = (value: unknown) => T;
