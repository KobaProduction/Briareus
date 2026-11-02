import type { FileWorkspacePort } from "./contracts";

export const MAX_FILE_TRANSFER = 64 * 1024 * 1024;
export const FILE_CHUNK_SIZE = 12288;
export function checkFileTransferSize(size: number): void {
  if (size > MAX_FILE_TRANSFER) throw new Error("Для файла больше 64 MiB используйте MCP Files");
}
/** Every chunk remains an independent owner-authorized call, with a stale scope guard. */
export async function downloadFileChunks(
  path: string,
  workspace: FileWorkspacePort,
  current: () => boolean,
): Promise<Uint8Array<ArrayBuffer>[] | null> {
  const info = await workspace.info(path);
  if (!current()) return null;
  checkFileTransferSize(info.size_bytes);
  const parts: Uint8Array<ArrayBuffer>[] = [];
  for (let offset = 0; offset < info.size_bytes; offset += FILE_CHUNK_SIZE) {
    if (!current()) return null;
    const length = Math.min(FILE_CHUNK_SIZE, info.size_bytes - offset);
    const part = await workspace.read({ path, offset, length });
    if (!current()) return null;
    if (
      part.path !== info.path ||
      part.size_bytes !== info.size_bytes ||
      part.bytes.length !== length
    )
      throw new Error("FILES_CHANGED_DURING_TRANSFER");
    parts.push(part.bytes);
  }
  return current() ? parts : null;
}
export async function uploadFileChunks(
  path: string,
  bytes: Uint8Array,
  workspace: FileWorkspacePort,
  current: () => boolean,
): Promise<boolean> {
  checkFileTransferSize(bytes.length);
  for (let offset = 0; offset < Math.max(bytes.length, 1); offset += FILE_CHUNK_SIZE) {
    if (!current()) return false;
    await workspace.write({
      path,
      bytes: bytes.subarray(offset, offset + FILE_CHUNK_SIZE),
      offset,
      truncate: offset === 0,
      create_parents: true,
    });
  }
  return current();
}
