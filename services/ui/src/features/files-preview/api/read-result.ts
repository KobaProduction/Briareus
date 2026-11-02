/** Native byte-response decoding and digest verification; no authority is inferred here. */
/** Native byte-response decoding and digest verification; no authority is inferred here. */
import { decodeBase64, recordValue } from "@/shared/lib/transport";

import { exactProjectionFields } from "@/shared/lib/owner-projection";
import {
  type FilesReadDecode,
  isCanonicalFilesPath,
  MAX_FILES_READ_BYTES,
  textProjection,
} from "../model/read-result";

interface ReadWire {
  size: number;
  sha256: string;
  base64: string;
}
function validBudget(maxBytes: number): boolean {
  return Number.isSafeInteger(maxBytes) && maxBytes >= 1 && maxBytes <= MAX_FILES_READ_BYTES;
}
function readWire(value: unknown, path: string, maxBytes: number): ReadWire | null {
  const row = recordValue(value);
  if (
    !row ||
    !exactProjectionFields(row, ["path", "size_bytes", "sha256", "content_base64"]) ||
    row.path !== path ||
    typeof row.size_bytes !== "number" ||
    !Number.isSafeInteger(row.size_bytes) ||
    row.size_bytes < 0 ||
    row.size_bytes > maxBytes
  )
    return null;
  if (
    typeof row.sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(row.sha256) ||
    typeof row.content_base64 !== "string"
  )
    return null;
  if (
    row.content_base64.length !== 4 * Math.ceil(row.size_bytes / 3) ||
    !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(row.content_base64)
  )
    return null;
  return { size: row.size_bytes, sha256: row.sha256, base64: row.content_base64 };
}
function decodedBytes(row: ReadWire): Uint8Array<ArrayBuffer> | null {
  const bytes = decodeBase64(row.base64);
  return bytes.length === row.size ? bytes : null;
}
export async function decodeFilesReadResult(
  value: unknown,
  expectedPath: string,
  signal?: AbortSignal,
  maxBytes = MAX_FILES_READ_BYTES,
): Promise<FilesReadDecode> {
  if (signal?.aborted) return { kind: "cancelled" };
  if (!isCanonicalFilesPath(expectedPath) || !validBudget(maxBytes)) return { kind: "invalid" };
  const row = readWire(value, expectedPath, maxBytes);
  if (!row) return { kind: "invalid" };
  if (typeof crypto === "undefined" || !crypto.subtle) return { kind: "unavailable" };
  try {
    const bytes = decodedBytes(row);
    if (!bytes) return { kind: "invalid" };
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    if (signal?.aborted) return { kind: "cancelled" };
    const hash = Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
    if (hash !== row.sha256) return { kind: "invalid" };
    return textProjection(bytes, { path: expectedPath, sizeBytes: bytes.length, sha256: hash });
  } catch {
    return { kind: "invalid" };
  }
}
