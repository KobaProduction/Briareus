/** Exact byte projection validation; owner/AgentSession authorization remains server-owned. */
export const MAX_FILES_READ_BYTES = 262_144;
export type FilesReadDecode =
  | { kind: "text"; path: string; sizeBytes: number; sha256: string; content: string }
  | { kind: "binary"; path: string; sizeBytes: number; sha256: string }
  | { kind: "invalid" | "unavailable" | "cancelled" };
const utf8 = new TextEncoder();
function canonicalSegment(part: string): boolean {
  return (
    part !== "" &&
    part !== "." &&
    part !== ".." &&
    utf8.encode(part).length <= 255 &&
    !/^\.upload-[0-9a-f]{32}\.tmp$/.test(part)
  );
}
function hasControl(text: string): boolean {
  return [...text].some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127);
}
export function isCanonicalFilesPath(path: string): boolean {
  if (
    typeof path !== "string" ||
    !path ||
    path.startsWith("/") ||
    path.includes("\\") ||
    hasControl(path) ||
    path.normalize("NFC") !== path
  )
    return false;
  const bytes = utf8.encode(path),
    parts = path.split("/");
  return (
    bytes.length <= 4096 &&
    new TextDecoder("utf-8", { ignoreBOM: true }).decode(bytes) === path &&
    parts.length <= 64 &&
    parts.every(canonicalSegment)
  );
}
export interface ReadMetadata {
  path: string;
  sizeBytes: number;
  sha256: string;
}
export function textProjection(bytes: Uint8Array, metadata: ReadMetadata): FilesReadDecode {
  try {
    const content = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
    const binary = [...content].some((char) => {
      const code = char.charCodeAt(0);
      return code <= 8 || code === 11 || code === 12 || (code >= 14 && code <= 31) || code === 127;
    });
    return binary ? { kind: "binary", ...metadata } : { kind: "text", ...metadata, content };
  } catch {
    return { kind: "binary", ...metadata };
  }
}
