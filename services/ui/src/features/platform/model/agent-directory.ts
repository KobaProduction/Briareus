import { canonicalUuid4 } from "./contracts";
export interface DirectoryAgent {
  id: string;
  project_uuid: string;
  parent_agent_id: string | null;
  name: string;
  enabled: boolean;
  created_at: string;
}
export interface AgentDirectoryPage {
  items: DirectoryAgent[];
  hasMore: boolean;
  nextCursor: string | null;
}
export interface AgentDirectoryPort {
  list(
    project: string,
    cursor: string | undefined,
    signal: AbortSignal,
  ): Promise<AgentDirectoryPage>;
  get(project: string, id: string, signal: AbortSignal): Promise<DirectoryAgent>;
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw Error("Invalid agent directory record");
  return value as Record<string, unknown>;
}
function uuid(value: unknown): string {
  if (typeof value !== "string" || !canonicalUuid4(value))
    throw Error("Invalid agent directory UUID");
  return value;
}
function decodeAgent(value: unknown, project: string): DirectoryAgent {
  const item = record(value),
    id = uuid(item.id),
    parent = item.parent_agent_id === null ? null : uuid(item.parent_agent_id);
  if (
    item.project_uuid !== project ||
    typeof item.name !== "string" ||
    item.name.length > 128 ||
    typeof item.enabled !== "boolean"
  )
    throw Error("Invalid agent directory identity");
  if (
    typeof item.created_at !== "string" ||
    !/(Z|[+-]\d{2}:\d{2})$/i.test(item.created_at) ||
    !Number.isFinite(Date.parse(item.created_at))
  )
    throw Error("Invalid agent directory time");
  return {
    id,
    project_uuid: project,
    parent_agent_id: parent,
    name: item.name,
    enabled: item.enabled,
    created_at: item.created_at,
  };
}
function advancingAgentKeys(
  items: readonly DirectoryAgent[],
  before: string | undefined,
): string | undefined {
  let previous = before;
  for (const item of items) {
    if (previous !== undefined && item.id <= previous)
      throw Error("Invalid agent directory progress");
    previous = item.id;
  }
  return previous;
}
export function decodeAgentDirectoryPage(
  value: unknown,
  project: string,
  before?: string,
): AgentDirectoryPage {
  const page = record(value);
  if (!Array.isArray(page.items) || page.items.length > 100 || typeof page.has_more !== "boolean")
    throw Error("Invalid agent directory page");
  const items = page.items.map((item) => decodeAgent(item, project)),
    last = advancingAgentKeys(items, before);
  const next = page.next_cursor === null ? null : uuid(page.next_cursor);
  if (page.has_more && (!items.length || next !== last))
    throw Error("Invalid agent directory cursor");
  return { items, hasMore: page.has_more, nextCursor: page.has_more ? next : null };
}
export function decodeAgentDirectoryDetail(
  value: unknown,
  project: string,
  id: string,
): DirectoryAgent {
  const item = decodeAgent(record(value).item, project);
  if (item.id !== id) throw Error("Invalid selected agent identity");
  return item;
}
/** Page traversal remains a read of the selected project. Each awaited page
 * must still belong to the same live owner epoch before another page starts. */
export async function readAgentDirectory(
  port: AgentDirectoryPort,
  project: string,
  signal: AbortSignal,
  current: () => boolean,
): Promise<DirectoryAgent[] | null> {
  const rows: DirectoryAgent[] = [];
  let cursor: string | undefined;
  do {
    const page = await port.list(project, cursor, signal);
    if (!current() || signal.aborted) return null;
    rows.push(...page.items);
    if (!page.hasMore) return rows;
    if (!page.nextCursor || page.nextCursor === cursor)
      throw Error("Invalid agent directory cursor");
    cursor = page.nextCursor;
  } while (cursor);
  return rows;
}
