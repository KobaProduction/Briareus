import { type BusEvent, eventProjectId } from "@/shared/events";

export const JOURNAL_PAGE_SIZE = 100;
export const JOURNAL_RETENTION_LIMIT = 20_000;
export interface JournalSelection {
  topics: string[];
  before: string | null;
  project_uuid: string | null;
  limit: number;
}
export interface JournalPage {
  items: BusEvent[];
  nextCursor: string | null;
  hasMore: boolean;
  retentionGap: boolean;
  retentionLimit: number;
}
export interface EventJournalPort {
  readonly history: readonly BusEvent[];
  readonly status: string;
  page(selection: JournalSelection): Promise<JournalPage>;
  subscribeResync(handler: () => void): () => void;
}

export function journalEventKey(event: BusEvent): string {
  return event.id ?? event.occurredAt + event.topic + event.type;
}
export function mergeJournalEvents(...groups: readonly (readonly BusEvent[])[]): BusEvent[] {
  const items = new Map<string, BusEvent>();
  for (const group of groups) for (const event of group) items.set(journalEventKey(event), event);
  return [...items.values()];
}
export function orderedJournalEvents(
  older: readonly BusEvent[],
  live: readonly BusEvent[],
): BusEvent[] {
  return mergeJournalEvents(older, live).sort(
    (a, b) => b.occurredAt.localeCompare(a.occurredAt) || (b.id ?? "").localeCompare(a.id ?? ""),
  );
}
export function matchesJournalSelection(
  event: BusEvent,
  topics: readonly string[],
  project: string | null,
): boolean {
  if (!topics.includes(event.topic)) return false;
  if (project === null) return true;
  return eventProjectId(event) === project;
}
