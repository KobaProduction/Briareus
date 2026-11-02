import { decodeJournalEvent } from "@/shared/events";
import { requireRecord } from "@/shared/lib/transport";
import {
  JOURNAL_PAGE_SIZE,
  JOURNAL_RETENTION_LIMIT,
  type JournalPage,
} from "../model/journal-policy";

function parseCursor(value: unknown): string {
  if (typeof value !== "string" || !/^\d{1,20}-\d{1,20}$/.test(value))
    throw Error("Invalid journal cursor");
  return value;
}
function cursorParts(value: string): readonly [bigint, bigint] {
  const [time, index] = value.split("-");
  if (time === undefined || index === undefined) throw Error("Invalid journal cursor");
  return [BigInt(time), BigInt(index)];
}
function olderCursor(next: unknown, before: string | null): string {
  const selected = parseCursor(next),
    current = cursorParts(selected);
  if (before !== null) {
    const previous = cursorParts(parseCursor(before));
    if (current[0] > previous[0] || (current[0] === previous[0] && current[1] >= previous[1])) {
      throw Error("Journal cursor did not advance");
    }
  }
  return selected;
}
/** Invisible rows can advance an empty page. Never derive progress from row count. */
export function decodeJournalPage(value: unknown, before: string | null): JournalPage {
  const page = requireRecord(value);
  if (
    !Array.isArray(page.items) ||
    page.items.length > JOURNAL_PAGE_SIZE ||
    typeof page.has_more !== "boolean" ||
    typeof page.retention_gap !== "boolean"
  ) {
    throw Error("Invalid journal page");
  }
  if (
    typeof page.retention_limit !== "number" ||
    !Number.isSafeInteger(page.retention_limit) ||
    page.retention_limit < 1 ||
    page.retention_limit > JOURNAL_RETENTION_LIMIT
  ) {
    throw Error("Invalid journal retention");
  }
  const nextCursor = page.next_cursor === null ? null : olderCursor(page.next_cursor, before);
  if (page.has_more && nextCursor === null) throw Error("Missing journal cursor");
  return {
    items: page.items.map(decodeJournalEvent),
    nextCursor,
    hasMore: page.has_more,
    retentionGap: page.retention_gap,
    retentionLimit: page.retention_limit,
  };
}
