import type { ManagedNode, ResourceLimits, ModuleCatalog } from "@/entities/node";
import type { Placement } from "./placement-intent";
import type { ProjectWorkspace } from "./project-workspace";
import type { NodeRuntimePolicy, NodeSetup } from "./node-replies";
import type { ModuleConfiguration } from "./module-configuration";
import type { ProjectWorkspaceMount } from "./project-workspace";

interface PlacementOptions {
  release_uuid: string;
  limits: ResourceLimits;
  configuration?: ModuleConfiguration;
  project_workspace?: ProjectWorkspaceMount | null;
}
export type PlacementMutation =
  | { action: "update"; update: PlacementOptions & { id: string; expected_sequence: number } }
  | {
      action: "place";
      placement: PlacementOptions & { id: string; node_uuid: string; name: string };
    };
export type ModuleCommand =
  | PlacementMutation
  | { action: "catalog" }
  | { action: "placements"; node_uuid?: string }
  | { action: "workspaces" | "ensure_workspace"; node_uuid: string }
  | { action: "recover"; recover: { id: string; expected_sequence: number } }
  | { action: "reconcile"; target_operation_uuid: string }
  | {
      action: "publish";
      publication: {
        id: string;
        module: string;
        source_commit: string;
        input_fingerprint: string;
        image: string;
        platform: string;
      };
    };

export type RuntimePolicyKey =
  | "execution_timeout_seconds"
  | "web_max_tabs"
  | "web_tab_idle_seconds"
  | "terminal_idle_seconds";
export type RuntimePolicyValues = Partial<Record<RuntimePolicyKey, number | null>>;
export interface RuntimePolicyWrite {
  operation_uuid: string;
  action: "runtime_policy";
  policy_scope: "server" | "node";
  node_uuid: string | null;
  policy_values: RuntimePolicyValues;
  expected_policy_sequence: number;
}
interface NodeRegistration {
  id: string;
  name: string;
  scope: ManagedNode["scope"];
  owner_uuid: string | null;
  host_uuid: string;
  runtime_uid: number;
  endpoint: string;
  budget: ManagedNode["budget"];
}
type NodeAction =
  | { action: "modules"; module: ModuleCommand }
  | { action: "runtime_policy_get"; policy_scope: "server" | "node"; node_uuid: string | null }
  | { action: "register"; registration: NodeRegistration }
  | {
      action: "budget";
      node_uuid: string;
      expected_sequence: number;
      budget: ManagedNode["budget"];
    }
  | { action: "rename"; node_uuid: string; expected_sequence: number; name: string }
  | { action: "setup" | "enable" | "disable"; node_uuid: string; expected_sequence: number }
  | { action: "pair"; node_uuid: string; expected_sequence: number; public_key: string };
export type NodeCommand = (NodeAction & { operation_uuid: string }) | RuntimePolicyWrite;

/** Application-facing transport boundary. The server owns authorization and
 * state transitions; callers retain explicit command ids and expected versions. */
export interface NodeGateway {
  command(projectUuid: string, command: NodeCommand): Promise<void>;
  inventory(projectUuid: string): Promise<ManagedNode[]>;
  catalog(projectUuid: string): Promise<ModuleCatalog>;
  placements(projectUuid: string, nodeUuid?: string): Promise<{ items: Placement[] }>;
  workspaces(projectUuid: string, nodeUuid: string): Promise<{ items: ProjectWorkspace[] }>;
  ensureWorkspace(
    projectUuid: string,
    nodeUuid: string,
    operationUuid: string,
  ): Promise<{ item: ProjectWorkspace }>;
  runtimePolicy(
    projectUuid: string,
    scope: "node" | "server",
    nodeUuid: string,
  ): Promise<{ runtime_policy: NodeRuntimePolicy }>;
  setup(
    projectUuid: string,
    node: ManagedNode,
    operationUuid: string,
  ): Promise<{ setup: NodeSetup }>;
}
