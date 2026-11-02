import { eventBus, RpcError } from "@/shared/events";
import { recordValue } from "@/shared/lib/transport";
import { isUuid4 } from "@/shared/lib/uuid";
import { PlatformCommandFailure } from "../model/administration-contracts";
import type { InvitationCapabilities, InvitationPort } from "../model/invitation-contracts";

function capabilities(value: unknown): InvitationCapabilities {
  const row = recordValue(value);
  if (
    !row ||
    typeof row.can_invite !== "boolean" ||
    typeof row.can_manage_inviters !== "boolean" ||
    !Array.isArray(row.inviter_ids) ||
    (row.unavailable_reason !== null && typeof row.unavailable_reason !== "string")
  )
    throw new Error("INVITATION_CAPABILITIES_INVALID");
  const ids = row.inviter_ids.map((id: unknown) => {
    if (!isUuid4(id)) throw new Error("INVITATION_CAPABILITIES_INVALID");
    return id;
  });
  return {
    can_invite: row.can_invite,
    can_manage_inviters: row.can_manage_inviters,
    inviter_ids: ids,
    unavailable_reason: row.unavailable_reason,
  };
}
export const invitationPort: InvitationPort = {
  capabilities: async (signal) =>
    eventBus.request(
      "platform.command",
      { operation_uuid: crypto.randomUUID(), action: "invitation.capabilities", data: {} },
      capabilities,
      signal,
    ),
  command: async (command, signal) => {
    try {
      await eventBus.execute("platform.command", { ...command }, signal);
    } catch (error) {
      throw new PlatformCommandFailure(
        error instanceof RpcError ? error.message : "UNAVAILABLE",
        error instanceof RpcError ? error.uncertain : true,
      );
    }
  },
  onChange: (listener) => eventBus.subscribe("management.events", () => listener()),
};
