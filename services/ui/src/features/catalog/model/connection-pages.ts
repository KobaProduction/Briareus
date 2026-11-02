import type { Connection, ConnectionPage } from "./connection-contracts"

type PageAdvance = { kind: "complete"; items: Connection[] } | { kind: "next"; cursor: string } | { kind: "invalid" }
/** Validate the complete owner scan before publishing any partial rows. */
export class ConnectionPages {
  private readonly rows: Connection[] = []
  private readonly ids = new Set<string>()
  private readonly cursors = new Set<string>()
  accept(page: ConnectionPage): PageAdvance {
    for (const row of page.items) {
      if (this.ids.has(row.id)) return { kind: "invalid" }
      this.ids.add(row.id)
      this.rows.push(row)
    }
    if (!page.hasMore) return { kind: "complete", items: this.rows }
    if (!page.nextCursor || this.cursors.has(page.nextCursor)) return { kind: "invalid" }
    this.cursors.add(page.nextCursor)
    return { kind: "next", cursor: page.nextCursor }
  }
}
