import type { ManagedProject } from "@/entities/project";
import type { ManagedTeam } from "@/entities/team";
import type { PlatformPerson } from "@/entities/user";
export interface PlatformInventory {
  users: PlatformPerson[];
  teams: ManagedTeam[];
  projects: ManagedProject[];
  truncated: boolean;
}
export interface EntityNameInput {
  name: string;
}
export interface EntityRenameInput extends EntityNameInput {
  id: string;
  expected_name: string;
}
export interface ProjectCreationInput extends EntityNameInput {
  team_id: string | null;
}
export interface TeamMemberInput {
  id: string;
  user_id: string;
}
export type ManagementIntent =
  | { action: "team.create"; data: EntityNameInput }
  | { action: "team.rename" | "project.rename"; data: EntityRenameInput }
  | { action: "team.member.add" | "team.member.remove"; data: TeamMemberInput }
  | { action: "project.create"; data: ProjectCreationInput };
export type ManagementAction = ManagementIntent["action"];
export type PlatformCommand = ManagementIntent & { operation_uuid: string };
export class PlatformCommandFailure extends Error {
  constructor(
    public code: string,
    public uncertain: boolean,
  ) {
    super(code);
  }
}

export interface PlatformAdministrationPort {
  inventory(signal: AbortSignal, teamId?: string): Promise<PlatformInventory>;
  command(command: PlatformCommand, signal: AbortSignal): Promise<void>;
  readPending(actor: string): PlatformCommand | null;
  storePending(actor: string, command: PlatformCommand | null): void;
  connected(): boolean;
  onManagement(listener: () => void): () => void;
  onResync(listener: () => void): () => void;
}
