import type { VerifiedPlatformContext } from "@/entities/workspace";
import { eventBus } from "@/shared/events";
import type { PlatformAdministrationPort } from "../model/administration-contracts";
import { usePlatformAdministration as useAdministration } from "../model/use-platform-administration";
import { readPendingAdministration, storePendingAdministration } from "./administration-recovery";
import { platformCommand, platformInventory } from "./platform-management";

const port: PlatformAdministrationPort = {
  inventory: platformInventory,
  command: platformCommand,
  readPending: readPendingAdministration,
  storePending: storePendingAdministration,
  connected: () => eventBus.state.status === "connected",
  onManagement: (listener) =>
    eventBus.subscribe("management.events", (event) => {
      if (/^(team\.|project\.|user\.)/.test(event.type)) listener();
    }),
  onResync: (listener) =>
    eventBus.subscribe("system.notifications", (event) => {
      if (event.type === "resync.required" || event.type === "source.recovered") listener();
    }),
};
export function usePlatformAdministration(
  context: () => VerifiedPlatformContext,
  onChanged: () => void,
) {
  return useAdministration(context, onChanged, port);
}
