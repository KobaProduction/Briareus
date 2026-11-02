import { CONTROL_PANEL_API_V1 } from "@/shared/config";
import { readBoundedJsonResponse } from "@/shared/lib/transport";
import type {
  FilesReadClientResult,
  FilesReadCommand,
  FilesReadPort,
  FilesReadSessionReference,
} from "../model/contracts";
import { readVerifiedContent } from "../model/verified-read";
import { decodeFilesReadResult } from "./read-result";

export type { FilesReadClientResult, FilesReadSessionReference } from "../model/contracts";

const DOMAIN = new TextEncoder().encode("files-project-relative-v1\0");
const LIMIT = 384 * 1024;
async function ownerSelector(project: string, path: string): Promise<string> {
  if (typeof crypto === "undefined" || !crypto.subtle)
    throw new Error("FILES_READ_SECURE_CONTEXT_REQUIRED");
  const raw = new TextEncoder().encode(path);
  const source = new Uint8Array(DOMAIN.length + raw.length);
  source.set(DOMAIN);
  source.set(raw, DOMAIN.length);
  const digest = await crypto.subtle.digest("SHA-256", source);
  const sha = Array.from(new Uint8Array(digest), (n) => n.toString(16).padStart(2, "0")).join("");
  return `project-path-v1:${project}:${sha}`;
}

function jsonMedia(reply: Response): boolean {
  return reply.headers.get("content-type")?.split(";", 1)[0]?.trim() === "application/json";
}
async function readBody(reply: Response, signal: AbortSignal, maxBytes = LIMIT): Promise<unknown> {
  const size = reply.headers.get("content-length");
  if (size !== null && (!/^\d{1,8}$/.test(size) || Number(size) > maxBytes))
    throw Error("untrusted file payload size");
  return readBoundedJsonResponse(reply, signal, maxBytes);
}
async function errorCode(reply: Response, signal: AbortSignal): Promise<string> {
  if (reply.headers.get("content-type")?.split(";", 1)[0]?.trim() !== "application/json")
    return "FILES_READ_UNAVAILABLE";
  try {
    const data = await readBody(reply, signal, 4096);
    if (data === null || typeof data !== "object" || Array.isArray(data))
      return "FILES_READ_UNAVAILABLE";
    const err = (data as Record<string, unknown>).error;
    if (err === null || typeof err !== "object" || Array.isArray(err))
      return "FILES_READ_UNAVAILABLE";
    const code = (err as Record<string, unknown>).code;
    return typeof code === "string" && /^[A-Z][A-Z_]{0,80}$/.test(code)
      ? code
      : "FILES_READ_UNAVAILABLE";
  } catch {
    return "FILES_READ_UNAVAILABLE";
  }
}

function readRefusal(status: number, code: string): FilesReadClientResult {
  const kinds: Partial<Record<number, "unauthorized" | "forbidden" | "invalid">> = {
    401: "unauthorized",
    403: "forbidden",
    422: "invalid",
  };
  return { kind: kinds[status] ?? "unavailable", code };
}
async function readFile(
  command: FilesReadCommand,
  signal: AbortSignal,
): Promise<FilesReadClientResult> {
  const response = await fetch(CONTROL_PANEL_API_V1 + "/files/read", {
    method: "POST",
    credentials: "same-origin",
    mode: "same-origin",
    cache: "no-store",
    redirect: "error",
    referrerPolicy: "no-referrer",
    signal,
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(command),
  });
  if (signal.aborted) return { kind: "cancelled", code: "FILES_READ_CANCELLED" };
  if (response.status !== 200)
    return readRefusal(response.status, await errorCode(response, signal));
  if (!jsonMedia(response)) return { kind: "invalid", code: "FILES_READ_RESPONSE_MEDIA_INVALID" };
  return decodeReply(await readBody(response, signal), command.path, command.max_bytes, signal);
}
const filesReadPort: FilesReadPort = { selector: ownerSelector, read: readFile };
/** Production composition: owner preflight and byte validation share one bounded HTTP adapter. */
export function readVerifiedFilesContent(
  source: FilesReadSessionReference,
  path: string,
  maxBytes: number,
  signal: AbortSignal,
): Promise<FilesReadClientResult> {
  return readVerifiedContent(source, path, maxBytes, signal, filesReadPort);
}

async function decodeReply(
  payload: unknown,
  path: string,
  maxBytes: number,
  signal: AbortSignal,
): Promise<FilesReadClientResult> {
  const decoded = await decodeFilesReadResult(payload, path, signal, maxBytes);
  if (decoded.kind === "text" || decoded.kind === "binary") return { kind: "ready", item: decoded };
  return {
    kind:
      decoded.kind === "cancelled"
        ? "cancelled"
        : decoded.kind === "unavailable"
          ? "unavailable"
          : "invalid",
    code: "FILES_READ_RESPONSE_NOT_VERIFIED",
  };
}
