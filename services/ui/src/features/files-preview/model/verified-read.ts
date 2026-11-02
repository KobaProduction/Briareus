import { isUuid4 } from "@/shared/lib/uuid";
import type { FilesReadClientResult, FilesReadPort, FilesReadSessionReference } from "./contracts";
import { isCanonicalFilesPath, MAX_FILES_READ_BYTES } from "./read-result";

function validRead(source: FilesReadSessionReference, path: string, maxBytes: number): boolean {
  return (
    isUuid4(source.project_uuid) &&
    isUuid4(source.session_uuid) &&
    source.status === "active" &&
    Number.isSafeInteger(source.revision) &&
    source.revision >= 1 &&
    Number.isSafeInteger(maxBytes) &&
    maxBytes >= 1 &&
    maxBytes <= MAX_FILES_READ_BYTES &&
    isCanonicalFilesPath(path) &&
    source.operations.includes("files.read") &&
    Number.isFinite(Date.parse(source.hard_expires_at)) &&
    Date.parse(source.hard_expires_at) > Date.now()
  );
}
function verifiedSelector(source: FilesReadSessionReference, selector: string): boolean {
  return source.resources.some(
    (scope) =>
      scope.hand === "files" &&
      scope.tool === "read_file" &&
      scope.action === "files.read" &&
      scope.resource.kind === "workspace_path" &&
      scope.resource.id === selector,
  );
}
const cancelled = (): FilesReadClientResult => ({
  kind: "cancelled",
  code: "FILES_READ_CANCELLED",
});
export async function readVerifiedContent(
  source: FilesReadSessionReference,
  path: string,
  maxBytes: number,
  signal: AbortSignal,
  port: FilesReadPort,
): Promise<FilesReadClientResult> {
  if (signal.aborted) return cancelled();
  if (!validRead(source, path, maxBytes))
    return { kind: "invalid", code: "FILES_READ_SCOPE_INVALID" };
  const command = {
    project_uuid: source.project_uuid,
    agent_session_uuid: source.session_uuid,
    expected_grant_revision: source.revision,
    path,
    max_bytes: maxBytes,
  };
  try {
    const selector = await port.selector(command.project_uuid, path);
    if (signal.aborted) return cancelled();
    if (!verifiedSelector(source, selector))
      return { kind: "invalid", code: "FILES_READ_SELECTOR_UNVERIFIED" };
    const reply = await port.read(command, signal);
    if (signal.aborted) return cancelled();
    return reply;
  } catch (error) {
    if (signal.aborted) return cancelled();
    return {
      kind: "unavailable",
      code:
        error instanceof Error && error.message === "FILES_READ_SECURE_CONTEXT_REQUIRED"
          ? error.message
          : "FILES_READ_UNAVAILABLE",
    };
  }
}
