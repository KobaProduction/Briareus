import type { SessionCommandPort } from "../model/contracts";
import { listCurrentSessions, readCurrentSession, revokeCurrentSession } from "./current-sessions";
import { executeNormalSessionOpen } from "./open-normal";

export const sessionCommands: SessionCommandPort = {
  list: listCurrentSessions,
  read: readCurrentSession,
  revoke: revokeCurrentSession,
  executeOpen: executeNormalSessionOpen,
};
