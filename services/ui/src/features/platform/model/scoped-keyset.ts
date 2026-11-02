import { canonicalUuid4 } from "./contracts";

/** Frontend presentation merge ONLY for already authenticated bounded
 * source keyset pages. A cursor, list item or locally filtered index does
 * not grant any permission, nor prove completeness outside `hasMore=false`.
 */
export interface PageContinuation<T> {
  items: readonly T[];
  nextAfterId?: string | null;
  hasMore?: boolean;
}
export interface VerifiedAppend<T> {
  rows: T[];
  next: string | null;
  hasMore: boolean;
}
function currentRowKeys<T>(rows: readonly T[], keyOf: (item: T) => string): Set<string> {
  const keys = new Set<string>();
  for (const row of rows) {
    const key = keyOf(row);
    if (!canonicalUuid4(key) || keys.has(key)) throw Error("Ambiguous current row");
    keys.add(key);
  }
  return keys;
}
function appendPageKeys<T>(
  items: readonly T[],
  after: string,
  keys: Set<string>,
  keyOf: (item: T) => string,
): string {
  let previous = after;
  for (const row of items) {
    const key = keyOf(row);
    if (!canonicalUuid4(key) || keys.has(key) || key <= previous)
      throw Error("Inconsistent authorized page cursor");
    keys.add(key);
    previous = key;
  }
  return previous;
}
function pageContinuation<T>(
  page: PageContinuation<T>,
  after: string,
  last: string,
): string | null {
  if (!page.hasMore) return null;
  const next = page.nextAfterId;
  if (!page.items.length || !next || !canonicalUuid4(next) || next !== last || next <= after)
    throw Error("Missing continuation for authorized page");
  return next;
}
export function appendVerifiedKeyset<T>(
  existing: readonly T[],
  page: PageContinuation<T>,
  after: string,
  keyOf: (item: T) => string,
): VerifiedAppend<T> {
  if (
    !canonicalUuid4(after) ||
    !Array.isArray(page.items) ||
    page.items.length > 100 ||
    typeof page.hasMore !== "boolean"
  )
    throw Error("Invalid authorized page");
  const last = appendPageKeys(page.items, after, currentRowKeys(existing, keyOf), keyOf);
  return {
    rows: [...existing, ...page.items],
    next: pageContinuation(page, after, last),
    hasMore: page.hasMore,
  };
}
