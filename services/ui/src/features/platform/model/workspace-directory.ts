import type {
  VerifiedPlatformContext,
  WorkspaceDirectoryRows,
  WorkspaceIdentity,
} from "@/entities/workspace";

export type WorkspaceDirectoryKind = "teams" | "projects";
export interface WorkspaceDirectoryPage {
  rows: WorkspaceDirectoryRows;
  hasMore: boolean;
  nextCursor: string | null;
}
export interface WorkspaceDirectoryPort {
  read(
    kind: WorkspaceDirectoryKind,
    cursor: string | undefined,
    proof: VerifiedPlatformContext,
    identity: WorkspaceIdentity,
    signal: AbortSignal,
  ): Promise<WorkspaceDirectoryPage>;
}
function advancingCursor(
  page: WorkspaceDirectoryPage,
  kind: WorkspaceDirectoryKind,
  cursor: string | undefined,
): string | null {
  let previous = cursor;
  const rows = kind === "teams" ? page.rows.teams : page.rows.projects;
  for (const row of rows) {
    if (previous !== undefined && row.id <= previous) throw Error("DIRECTORY_PROGRESS_INVALID");
    previous = row.id;
  }
  if (!page.hasMore) return null;
  if (!rows.length || page.nextCursor !== previous) throw Error("DIRECTORY_CURSOR_INVALID");
  return page.nextCursor;
}
async function collectKind(
  port: WorkspaceDirectoryPort,
  kind: WorkspaceDirectoryKind,
  proof: VerifiedPlatformContext,
  identity: WorkspaceIdentity,
  signal: AbortSignal,
  current: () => boolean,
): Promise<WorkspaceDirectoryRows | null> {
  const result: WorkspaceDirectoryRows = { teams: [], projects: [] };
  let cursor: string | undefined;
  do {
    if (signal.aborted || !current()) return null;
    const page = await port.read(kind, cursor, proof, identity, signal);
    if (signal.aborted || !current()) return null;
    const next = advancingCursor(page, kind, cursor);
    result.teams.push(...page.rows.teams);
    result.projects.push(...page.rows.projects);
    if (next === null) return result;
    cursor = next;
  } while (cursor);
  return result;
}
/** Read one current owner snapshot. Monotonic UUID keysets reject cycles
 * without retaining an unbounded collection of previously seen cursors. */
export async function readWorkspaceDirectory(
  port: WorkspaceDirectoryPort,
  proof: VerifiedPlatformContext,
  identity: WorkspaceIdentity,
  signal: AbortSignal,
  current: () => boolean,
): Promise<WorkspaceDirectoryRows | null> {
  const teams = await collectKind(port, "teams", proof, identity, signal, current);
  if (!teams || signal.aborted || !current()) return null;
  const projects = await collectKind(
    port, "projects", { ...proof, teams: teams.teams }, identity, signal, current,
  );
  return projects && current() && !signal.aborted
    ? { teams: teams.teams, projects: projects.projects }
    : null;
}
