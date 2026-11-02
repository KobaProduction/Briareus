import { eventBus } from "@/shared/events";
import type { NodeCommand, NodeGateway } from "../model/node-commands";
import { decodeRuntimePolicy } from "./configuration-replies";
import { decodeModuleCatalog } from "./module-replies";
import { decodeNodeInventory } from "./node-inventory-replies";
import { decodeNodeSetup } from "./node-setup-replies";
import { decodeEnsuredWorkspace, decodePlacements, decodeWorkspaces } from "./placement-replies";

async function request<T>(
  projectUuid: string,
  command: NodeCommand,
  decode: (value: unknown) => T,
): Promise<T> {
  return eventBus.request("nodes.command", { ...command, project_uuid: projectUuid }, decode);
}
function moduleRead(
  action: "catalog" | "placements" | "workspaces",
  nodeUuid?: string,
): NodeCommand {
  if (action === "catalog")
    return { operation_uuid: crypto.randomUUID(), action: "modules", module: { action } };
  if (action === "workspaces") {
    if (!nodeUuid) throw Error("NODE_REQUIRED");
    return {
      operation_uuid: crypto.randomUUID(),
      action: "modules",
      module: { action, node_uuid: nodeUuid },
    };
  }
  return {
    operation_uuid: crypto.randomUUID(),
    action: "modules",
    module: { action, ...(nodeUuid ? { node_uuid: nodeUuid } : {}) },
  };
}
export const nodeGateway: NodeGateway = {
  async command(projectUuid, command) {
    await eventBus.execute("nodes.command", { ...command, project_uuid: projectUuid });
  },
  async inventory(projectUuid) {
    return eventBus.request("nodes.inventory", { project_uuid: projectUuid }, decodeNodeInventory);
  },
  async catalog(projectUuid) {
    return request(projectUuid, moduleRead("catalog"), decodeModuleCatalog);
  },
  async placements(projectUuid, nodeUuid) {
    return request(projectUuid, moduleRead("placements", nodeUuid), (value) =>
      decodePlacements(value, {
        projectId: projectUuid,
        nodeId: nodeUuid,
      }),
    );
  },
  async workspaces(projectUuid, nodeUuid) {
    return request(projectUuid, moduleRead("workspaces", nodeUuid), (value) =>
      decodeWorkspaces(value, projectUuid, nodeUuid),
    );
  },
  async ensureWorkspace(projectUuid, nodeUuid, operationUuid) {
    return request(
      projectUuid,
      {
        operation_uuid: operationUuid,
        action: "modules",
        module: { action: "ensure_workspace", node_uuid: nodeUuid },
      },
      (value) => decodeEnsuredWorkspace(value, projectUuid, nodeUuid),
    );
  },
  async runtimePolicy(projectUuid, scope, nodeUuid) {
    return request(
      projectUuid,
      {
        operation_uuid: crypto.randomUUID(),
        action: "runtime_policy_get",
        policy_scope: scope,
        node_uuid: scope === "node" ? nodeUuid : null,
      },
      (value) => decodeRuntimePolicy(value, scope, nodeUuid),
    );
  },
  async setup(projectUuid, node, operationUuid) {
    return request(
      projectUuid,
      {
        operation_uuid: operationUuid,
        action: "setup",
        node_uuid: node.id,
        expected_sequence: node.sequence,
      },
      (value) => decodeNodeSetup(value, node),
    );
  },
};
export const nodeCommand = nodeGateway.command;
export const nodeInventory = nodeGateway.inventory;
