import { onScopeDispose, ref, watch } from "vue";
import type { TerminalJobHistory } from "./job-history";
import type { TerminalJobStatus } from "./terminal-result";

interface HistoryContext {
  project: () => string | null;
  identity: () => string;
  enabled: () => boolean;
}
export type TerminalHistoryPort = (
  project: string,
  signal: AbortSignal,
) => Promise<TerminalJobHistory>;

export function useJobHistory(context: HistoryContext, history: TerminalHistoryPort | undefined) {
  const jobs = ref<TerminalJobStatus[]>([]);
  const jobsLoading = ref(false),
    jobsNotice = ref(""),
    historyLoaded = ref(false);
  let disposed = false;
  let generation = 0,
    controller: AbortController | null = null;
  function current(run: number) {
    return !disposed && run === generation && context.enabled();
  }
  function clear() {
    ++generation;
    controller?.abort();
    jobs.value = [];
    jobsLoading.value = false;
    jobsNotice.value = "";
    historyLoaded.value = false;
  }
  function apply(result: TerminalJobHistory) {
    jobs.value = result.jobs;
    historyLoaded.value = true;
    jobsNotice.value = result.truncated
      ? `Показаны последние ${result.jobs.length} из ${result.total} заданий.`
      : "";
  }
  async function refreshJobs(): Promise<void> {
    if (disposed) return;
    const project = context.project();
    if (!project || !history || !context.enabled() || jobsLoading.value) return;
    const request = new AbortController(),
      run = generation;
    controller = request;
    jobsLoading.value = true;
    jobsNotice.value = "";
    try {
      const result = await history(project, request.signal);
      if (current(run)) apply(result);
    } catch {
      if (current(run)) jobsNotice.value = "Не удалось получить задания проекта. Обновите список.";
    } finally {
      if (current(run)) jobsLoading.value = false;
    }
  }
  watch([context.identity, context.enabled], clear, { immediate: true, flush: "sync" });
  onScopeDispose(() => {
    disposed = true;
    clear();
  });
  return { jobs, jobsLoading, jobsNotice, historyLoaded, refreshJobs };
}
