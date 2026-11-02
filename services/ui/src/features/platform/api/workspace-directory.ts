import { decodeDirectoryRows } from "@/entities/workspace";
import { eventBus } from "@/shared/events";
import { requireRecord } from "@/shared/lib/transport";
import { isUuid4 } from "@/shared/lib/uuid";
import type { WorkspaceDirectoryPort } from "../model/workspace-directory";

export const workspaceDirectoryPort: WorkspaceDirectoryPort = {
  async read(kind, cursor, proof, identity, signal) {
    return eventBus.request(
      "platform.directory",
      { kind, ...(cursor ? { cursor } : {}), limit: 100 },
      (value) => {
        const page = requireRecord(value);
        if (page.kind !== kind || typeof page.has_more !== "boolean")
          throw Error("DIRECTORY_RESPONSE_INVALID");
        const rows = decodeDirectoryRows(kind, page.items, proof, identity);
        const next = page.next_cursor;
        if (!rows || !(next === null || isUuid4(next))) throw Error("DIRECTORY_RESPONSE_INVALID");
        if (!page.has_more && next !== null) throw Error("DIRECTORY_CURSOR_INVALID");
        return { rows, hasMore: page.has_more, nextCursor: next };
      },
      signal,
    );
  },
};
