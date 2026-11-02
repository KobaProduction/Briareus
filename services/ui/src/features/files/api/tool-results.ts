import { decodeBase64, requireRecord } from "@/shared/lib/transport";

import type {
  FileChunk,
  FileEntry,
  FileHash,
  FileInformation,
  FilePage,
  FileReadQuery,
  FileWriteChunk,
  FileWriteReceipt,
} from "../model/contracts";

function integer(value: unknown, code: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw new Error(code);
  return value;
}
function text(value: unknown, code: string): string {
  if (typeof value !== "string") throw new Error(code);
  return value;
}
function flag(value: unknown, code: string): boolean {
  if (typeof value !== "boolean") throw new Error(code);
  return value;
}
export function fileInformation(value: unknown): FileInformation {
  const row = requireRecord(value);
  if (row.type !== "file" && row.type !== "directory") throw new Error("FILES_INFO_INVALID");
  // Nanosecond filesystem timestamps exceed JS's safe-integer range; they are
  // descriptive metadata, never a revision or a resource-identity proof.
  if (typeof row.modified_at_ns !== "number" || !Number.isInteger(row.modified_at_ns))
    throw new Error("FILES_INFO_INVALID");
  return {
    path: text(row.path, "FILES_INFO_INVALID"),
    name: text(row.name, "FILES_INFO_INVALID"),
    type: row.type,
    size_bytes: integer(row.size_bytes, "FILES_INFO_INVALID"),
    modified_at_ns: row.modified_at_ns,
    ...(row.mime_type === undefined
      ? {}
      : { mime_type: text(row.mime_type, "FILES_INFO_INVALID") }),
  };
}
export function filePage(value: unknown): FilePage {
  const row = requireRecord(value);
  if (!Array.isArray(row.entries)) throw new Error("FILES_LIST_INVALID");
  const entries: FileEntry[] = row.entries.map(fileInformation);
  const page: FilePage = {
    path: text(row.path, "FILES_LIST_INVALID"),
    entries,
    count: integer(row.count, "FILES_LIST_INVALID"),
    total: integer(row.total, "FILES_LIST_INVALID"),
    offset: integer(row.offset, "FILES_LIST_INVALID"),
    limit: integer(row.limit, "FILES_LIST_INVALID"),
    truncated: flag(row.truncated, "FILES_LIST_INVALID"),
  };
  if (
    page.limit < 1 ||
    page.limit > 1000 ||
    page.count !== entries.length ||
    page.count > page.limit
  )
    throw new Error("FILES_LIST_INVALID");
  return page;
}
export function fileChunk(value: unknown, query: FileReadQuery): FileChunk {
  const row = requireRecord(value);
  const base64 = text(row.data_base64, "FILES_READ_INVALID");
  if (base64.length > 4 * Math.ceil(query.length / 3)) throw new Error("FILES_CHUNK_TOO_LARGE");
  const chunk: FileChunk = {
    path: text(row.path, "FILES_READ_INVALID"),
    offset: integer(row.offset, "FILES_READ_INVALID"),
    bytes_read: integer(row.bytes_read, "FILES_READ_INVALID"),
    next_offset: integer(row.next_offset, "FILES_READ_INVALID"),
    size_bytes: integer(row.size_bytes, "FILES_READ_INVALID"),
    eof: flag(row.eof, "FILES_READ_INVALID"),
    bytes: decodeBase64(base64),
  };
  if (
    chunk.offset !== query.offset ||
    chunk.bytes_read !== chunk.bytes.length ||
    chunk.bytes_read > query.length ||
    chunk.next_offset !== chunk.offset + chunk.bytes_read
  )
    throw new Error("FILES_READ_INVALID");
  return chunk;
}
export function fileHash(value: unknown): FileHash {
  const row = requireRecord(value),
    sha256 = text(row.sha256, "FILES_HASH_INVALID");
  if (!/^[a-f0-9]{64}$/.test(sha256)) throw new Error("FILES_HASH_INVALID");
  return { path: text(row.path, "FILES_HASH_INVALID"), sha256 };
}
export function fileWritten(value: unknown, command: FileWriteChunk): FileWriteReceipt {
  const row = requireRecord(value);
  const written: FileWriteReceipt = {
    path: text(row.path, "FILES_WRITE_INVALID"),
    bytes_written: integer(row.bytes_written, "FILES_WRITE_INVALID"),
    next_offset: integer(row.next_offset, "FILES_WRITE_INVALID"),
    size_bytes: integer(row.size_bytes, "FILES_WRITE_INVALID"),
  };
  if (
    written.bytes_written !== command.bytes.length ||
    written.next_offset !== command.offset + written.bytes_written ||
    written.size_bytes !== written.next_offset
  )
    throw new Error("FILES_WRITE_OUTCOME_UNKNOWN");
  return written;
}
