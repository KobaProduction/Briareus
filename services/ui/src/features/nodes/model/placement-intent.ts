import type { ResourceLimits } from "@/entities/node";
import type { ModuleConfiguration } from "./module-configuration";
import type { ProjectWorkspaceMount } from "./project-workspace";
import type { PlacementOperation as PlacementOperationData } from "./operation-presentation";
export interface Placement {
  runtime_policy_pending?: boolean;
  id: string;
  name: string;
  module: string;
  state: string;
  sequence: number;
  release_uuid: string;
  limits: ResourceLimits;
  workspace_uuid: string | null;
  configuration?: ModuleConfiguration | null;
  project_workspace?: ProjectWorkspaceMount | null;
  operation: PlacementOperationData | null;
}

import type { PlacementMutation } from "./node-commands";
import { placementConfigurationField } from "./placement-edit";
import { projectWorkspaceField } from "./project-workspace";
export interface PlacementEditIntent {
  updating: Placement | null;
  module: string;
  configuration: ModuleConfiguration;
  workspace: ProjectWorkspaceMount | null;
  limits: ResourceLimits;
  release: string;
  placementId: string;
  nodeId: string;
  name: string;
}
export function placementMutation(input: PlacementEditIntent): PlacementMutation {
  const configurable = input.updating
    ? placementConfigurationField(input.module, input.updating.configuration, input.configuration)
    : ["web", "serena"].includes(input.module)
      ? { configuration: input.configuration }
      : {};
  const workspace = projectWorkspaceField(
    input.module,
    input.updating?.project_workspace,
    input.workspace,
    !!input.updating,
  );
  const limits = input.limits;
  const module: PlacementMutation = input.updating
    ? {
        action: "update",
        update: {
          id: input.updating.id,
          release_uuid: input.release,
          expected_sequence: input.updating.sequence,
          limits,
          ...configurable,
          ...workspace,
        },
      }
    : {
        action: "place",
        placement: {
          id: input.placementId,
          node_uuid: input.nodeId,
          release_uuid: input.release,
          name: input.name.trim(),
          limits,
          ...configurable,
          ...workspace,
        },
      };
  return module;
}

import { operationInProgress } from "./operation-presentation";
export function placementResumeAllowed(row: Pick<Placement, "state" | "operation">): boolean {
  return !!row.operation?.reconciliation_required && ["pending", "updating"].includes(row.state);
}

export function placementRecoveryAllowed(row: Placement, enabled: boolean, busy: boolean): boolean {
  return (
    !busy &&
    enabled &&
    !operationInProgress(row.operation) &&
    (!row.operation?.reconciliation_required || placementResumeAllowed(row))
  );
}
