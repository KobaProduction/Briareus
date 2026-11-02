import { computed, ref, watch, onScopeDispose, type Ref } from "vue";
import type { BusEvent } from "@/shared/events";
import {
  JOURNAL_PAGE_SIZE,
  JOURNAL_RETENTION_LIMIT,
  journalEventKey,
  matchesJournalSelection,
  mergeJournalEvents,
  orderedJournalEvents,
  type EventJournalPort,
  type JournalPage,
  type JournalSelection,
} from "./journal-policy";

export function useEventJournal(
  topics: Ref<string[]>,
  project: Ref<string | null>,
  identity: Ref<string>,
  port: EventJournalPort,
) {
  const older = ref<BusEvent[]>([]),
    live = ref<BusEvent[]>([]),
    atTop = ref(true),
    busy = ref(false),
    error = ref("");
  const more = ref(true),
    gap = ref(false),
    retention = ref(JOURNAL_RETENTION_LIMIT);
  let cursor: string | null = null,
    generation = 0,
    catching: number | null = null,
    disposed = false,
    recoveryPending = false;
  const current = (run: number): boolean => !disposed && run === generation;
  const pending = computed(() => {
    const visible = new Set(live.value.map(journalEventKey));
    return port.history.filter(
      (event) =>
        matchesJournalSelection(event, topics.value, project.value) &&
        !visible.has(journalEventKey(event)),
    ).length;
  });
  const source = computed(() => orderedJournalEvents(older.value, live.value));
  function selection(before: string | null): JournalSelection {
    return {
      topics: [...topics.value],
      before,
      project_uuid: project.value,
      limit: JOURNAL_PAGE_SIZE,
    };
  }
  function acceptPage(page: JournalPage): void {
    older.value = mergeJournalEvents(older.value, page.items);
    gap.value ||= page.retentionGap;
    retention.value = page.retentionLimit;
  }
  function recoverAfterRead(): void {
    if (recoveryPending && port.status === "connected") void catchUp();
  }
  async function load(): Promise<void> {
    if (busy.value || catching !== null || !more.value || port.status !== "connected" || disposed)
      return;
    busy.value = true;
    error.value = "";
    const run = generation,
      request = selection(cursor);
    try {
      const page = await port.page(request);
      if (!current(run)) return;
      acceptPage(page);
      cursor = page.nextCursor;
      more.value = page.hasMore;
    } catch {
      if (current(run)) error.value = "Не удалось загрузить продолжение журнала.";
    } finally {
      if (current(run)) {
        busy.value = false;
        recoverAfterRead();
      }
    }
  }
  async function restorePages(run: number): Promise<void> {
    const known = new Set(older.value.map(journalEventKey));
    let before: string | null = null,
      pages = 0;
    // The existing server retains at most 20,000 rows and returns up to 100
    // visible events per page (or scans 2,000 invisible rows). A valid scan
    // therefore fits this bound, including a final empty page.
    const maximumPages = Math.ceil(retention.value / JOURNAL_PAGE_SIZE) + 1;
    while (current(run)) {
      if (++pages > maximumPages) throw Error("Journal recovery exceeded retention bound");
      const page = await port.page(selection(before));
      if (!current(run)) return;
      const overlap = page.items.some((event) => known.has(journalEventKey(event)));
      acceptPage(page);
      if (overlap || !page.hasMore) return;
      before = page.nextCursor;
    }
  }
  async function catchUp(): Promise<void> {
    if (disposed || port.status !== "connected") return;
    if (catching !== null || busy.value) {
      recoveryPending = true;
      return;
    }
    recoveryPending = false;
    if (!older.value.length) {
      cursor = null;
      more.value = true;
      await load();
      return;
    }
    const run = generation;
    catching = run;
    try {
      await restorePages(run);
    } catch {
      if (current(run)) error.value = "Не удалось восстановить пропущенные события.";
    } finally {
      finishRecovery(run);
    }
  }
  function finishRecovery(run: number): void {
    if (!current(run) || catching !== run) return;
    catching = null;
    recoverAfterRead();
  }
  function resetScope(): void {
    generation++;
    catching = null;
    recoveryPending = false;
    older.value = [];
    live.value = [...port.history];
    cursor = null;
    more.value = true;
    busy.value = false;
    error.value = "";
    gap.value = false;
    void load();
  }
  watch(
    () => [port.history[0]?.id, port.history.length, atTop.value],
    () => {
      if (atTop.value) live.value = [...port.history];
    },
    { immediate: true },
  );
  watch(() => [topics.value.join(","), project.value, identity.value], resetScope, {
    immediate: true,
    flush: "sync",
  });
  watch(
    () => port.status,
    (status) => {
      // Fence even a successful old-socket reply before reconnect recovery starts.
      generation++;
      catching = null;
      busy.value = false;
      recoveryPending = true;
      if (status === "connected") void catchUp();
    },
    { flush: "sync" },
  );
  const stop = port.subscribeResync(() => {
    void catchUp();
  });
  onScopeDispose(() => {
    disposed = true;
    generation++;
    stop();
  });
  function showLatest(): void {
    atTop.value = true;
    live.value = [...port.history];
  }
  return { source, busy, error, more, gap, retention, atTop, pending, load, showLatest };
}
