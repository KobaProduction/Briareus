import { CONTROL_PANEL_AUTH_API } from "@/shared/config";
import { readBoundedErrorCode, readBoundedJsonResponse } from "@/shared/lib/transport";
import { isUuid4 } from "@/shared/lib/uuid";
import type { VerifiedPlatformContext, WorkspaceIdentity } from "../model/proof";
import { validatePlatformContext } from "../model/verify";
export type PlatformContextState =
  | { kind: "verified"; context: VerifiedPlatformContext }
  | { kind: "signed_out" | "expired" | "denied" | "not_current" }
  | { kind: "unavailable"; code: string }
  | { kind: "invalid_response" };

const ROUTE = `${CONTROL_PANEL_AUTH_API}/me`;
function exactProject(proof: VerifiedPlatformContext, projectUuid: string | undefined): boolean {
  return (
    projectUuid === undefined ||
    (proof.projects.length === 1 &&
      proof.projects[0]?.id === projectUuid &&
      proof.teams.length <= 1)
  );
}
async function decodeContext(
  response: Response,
  identity: WorkspaceIdentity,
  signal: AbortSignal,
  projectUuid: string | undefined,
): Promise<PlatformContextState> {
  if (response.status === 200) {
    const proof = validatePlatformContext(
      await readBoundedJsonResponse(response, signal, 262_144),
      identity,
    );
    if (signal.aborted) return { kind: "unavailable", code: "PLATFORM_READ_CANCELLED" };
    if (!proof || !exactProject(proof, projectUuid)) return { kind: "invalid_response" };
    return { kind: "verified", context: proof };
  }
  const code = await readBoundedErrorCode(response, signal);
  if (signal.aborted) return { kind: "unavailable", code: "PLATFORM_READ_CANCELLED" };
  if (response.status === 401)
    return { kind: code === "OIDC_SESSION_EXPIRED" ? "expired" : "signed_out" };
  if (response.status === 403)
    return { kind: code === "PLATFORM_MEMBERSHIP_NOT_CURRENT" ? "not_current" : "denied" };
  return { kind: "unavailable", code };
}
async function readContext(
  identity: WorkspaceIdentity,
  signal: AbortSignal,
  projectUuid?: string,
): Promise<PlatformContextState> {
  if (projectUuid !== undefined && !isUuid4(projectUuid)) return { kind: "invalid_response" };
  if (signal.aborted) return { kind: "unavailable", code: "PLATFORM_READ_CANCELLED" };
  try {
    const response = await fetch(
      projectUuid === undefined ? ROUTE : `${ROUTE}?project_uuid=${projectUuid}`,
      {
        method: "GET",
        credentials: "same-origin",
        mode: "same-origin",
        signal,
        redirect: "error",
        cache: "no-store",
        referrerPolicy: "no-referrer",
        headers: { Accept: "application/json" },
      },
    );
    if (signal.aborted) return { kind: "unavailable", code: "PLATFORM_READ_CANCELLED" };
    return await decodeContext(response, identity, signal, projectUuid);
  } catch {
    return {
      kind: "unavailable",
      code: signal.aborted ? "PLATFORM_READ_CANCELLED" : "NETWORK_UNAVAILABLE",
    };
  }
}

/** Bounded navigation inventory; never a substitute for an exact Project
 * owner read immediately before a Project-scoped management command. */
export function readPlatformContext(
  identity: WorkspaceIdentity,
  signal: AbortSignal,
): Promise<PlatformContextState> {
  return readContext(identity, signal);
}
/** Source-backed exact Project read added by Backend's membership router.
 * Do not fall back to the capped inventory if this request is unavailable. */
export function readProjectContext(
  identity: WorkspaceIdentity,
  projectUuid: string,
  signal: AbortSignal,
): Promise<PlatformContextState> {
  return readContext(identity, signal, projectUuid);
}
