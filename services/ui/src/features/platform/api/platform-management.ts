import type { ManagedProject } from "@/entities/project";
import type { ManagedTeam } from "@/entities/team";
import type { PlatformPerson } from "@/entities/user";
import { eventBus, RpcError } from "@/shared/events";
import { decodePlatformInventory } from "../model/administration-projection";

export type { ManagedProject, ManagedTeam, PlatformPerson };

import {
  type PlatformCommand,
  PlatformCommandFailure,
  type PlatformInventory,
} from "../model/administration-contracts";

export type {
  ManagementAction,
  PlatformCommand,
  PlatformInventory,
} from "../model/administration-contracts";
export { PlatformCommandFailure } from "../model/administration-contracts";
export async function platformInventory(
  signal: AbortSignal,
  teamId?: string,
): Promise<PlatformInventory> {
  try {
    return await eventBus.request(
      teamId ? "platform.team" : "platform.inventory",
      teamId ? { id: teamId } : {},
      decodePlatformInventory,
      signal,
    );
  } catch (error) {
    throw new PlatformCommandFailure(
      error instanceof RpcError ? error.message : "UNAVAILABLE",
      false,
    );
  }
}
export async function platformCommand(
  command: PlatformCommand,
  signal: AbortSignal,
): Promise<void> {
  try {
    await eventBus.execute("platform.command", { ...command }, signal);
  } catch (error) {
    throw new PlatformCommandFailure(
      error instanceof RpcError ? error.message : "NETWORK_UNAVAILABLE",
      error instanceof RpcError ? error.uncertain : true,
    );
  }
}
