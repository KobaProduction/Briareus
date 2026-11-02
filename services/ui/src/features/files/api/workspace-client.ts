import { eventBus, readHandResources } from "@/shared/events";
import { encodeBase64, mcpValue } from "@/shared/lib/transport";

import type { FileListQuery, FileReadQuery, FileWorkspacePort } from "../model/contracts";
import { fileChunk, fileHash, fileInformation, filePage, fileWritten } from "./tool-results";

export interface FileCommandContext {
  project_uuid: string;
  signal?: AbortSignal;
}
type FileToolRequest =
  | { tool: "file_info" | "file_hash"; arguments: { path: string } }
  | { tool: "file_list"; arguments: FileListQuery }
  | { tool: "file_read"; arguments: FileReadQuery }
  | {
      tool: "file_write";
      arguments: {
        path: string;
        data_base64: string;
        offset: number;
        truncate: boolean;
        create_parents: boolean;
      };
    };

/** Each call obtains fresh UI context; Gateway/Hands remain the sole execution authority. */
export function createFilesClient(source: () => FileCommandContext | null): FileWorkspacePort {
  async function exchange<T>(call: FileToolRequest, decode: (value: unknown) => T): Promise<T> {
    const context = source();
    if (!context) throw new Error("Выберите проект с доступом к файлам");
    const { signal, project_uuid } = context;
    return eventBus.request(
      "files.command",
      { project_uuid, operation_uuid: crypto.randomUUID(), ...call },
      (value) => mcpValue(value, decode),
      signal,
    );
  }
  return {
    info: async (path) => exchange({ tool: "file_info", arguments: { path } }, fileInformation),
    list: async (query) => {
      const page = await exchange({ tool: "file_list", arguments: query }, filePage);
      if (page.offset !== query.offset || page.limit !== query.limit)
        throw new Error("FILES_LIST_INVALID");
      return page;
    },
    read: async (query) =>
      exchange({ tool: "file_read", arguments: query }, (value) => fileChunk(value, query)),
    hash: async (path) => exchange({ tool: "file_hash", arguments: { path } }, fileHash),
    write: async (command) =>
      exchange(
        {
          tool: "file_write",
          arguments: {
            path: command.path,
            data_base64: encodeBase64(command.bytes),
            offset: command.offset,
            truncate: command.truncate,
            create_parents: command.create_parents,
          },
        },
        (value) => fileWritten(value, command),
      ),
  };
}
export async function filesResources(project: string, signal: AbortSignal) {
  const scopes = await readHandResources(
    "files.resources",
    project,
    ["files.read", "files.write"],
    signal,
  );
  if (!scopes?.length || scopes.some((item) => item.hand !== "files"))
    throw new Error("FILES_SCOPE_INVALID");
  return scopes;
}
