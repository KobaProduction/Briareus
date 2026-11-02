import type { FileEntry, FileInformation, FilePage, FileWorkspacePort } from "./contracts";
import { FILE_CHUNK_SIZE } from "./transfer";

export type FileReadTool = "file_list" | "file_read" | "file_info" | "file_hash";
export type FileView =
  | { kind: "directory"; entries: FileEntry[] }
  | { kind: "content"; bytes: Uint8Array<ArrayBuffer>; complete: boolean }
  | { kind: "hash"; sha256: string }
  | { kind: "information"; info: FileInformation };

async function readDirectory(
  page: FilePage,
  path: string,
  workspace: FileWorkspacePort,
  current: () => boolean,
): Promise<FileView | null> {
  const entries = [...page.entries];
  while (entries.length < page.total) {
    if (!current()) return null;
    const next = await workspace.list({ path, offset: entries.length, limit: 50 });
    if (!current()) return null;
    if (!next.entries.length) break;
    entries.push(...next.entries);
  }
  return current() ? { kind: "directory", entries } : null;
}
async function readContent(
  path: string,
  workspace: FileWorkspacePort,
  current: () => boolean,
): Promise<FileView | null> {
  const read = await workspace.read({ path, offset: 0, length: FILE_CHUNK_SIZE });
  if (!current()) return null;
  const info = await workspace.info(path);
  return current()
    ? {
        kind: "content",
        bytes: read.bytes,
        complete: read.path === info.path && read.eof && read.bytes.length === info.size_bytes,
      }
    : null;
}
/** Read a typed view, publishing nothing after the current scope changes. */
export async function readFileView(
  tool: FileReadTool,
  path: string,
  workspace: FileWorkspacePort,
  current: () => boolean,
): Promise<FileView | null> {
  switch (tool) {
    case "file_list": {
      const page = await workspace.list({ path, offset: 0, limit: 50 });
      return current() ? readDirectory(page, path, workspace, current) : null;
    }
    case "file_read":
      return readContent(path, workspace, current);
    case "file_hash": {
      const hash = await workspace.hash(path);
      return current() ? { kind: "hash", sha256: hash.sha256 } : null;
    }
    case "file_info": {
      const info = await workspace.info(path);
      return current() ? { kind: "information", info } : null;
    }
  }
}
