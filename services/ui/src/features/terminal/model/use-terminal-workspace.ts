import { computed, onBeforeUnmount, ref, watch } from "vue";
import type { VerifiedPlatformContext } from "@/entities/workspace";
import { eventProjectId } from "@/shared/events";
import type { HandEffectScope } from "@/shared/lib/hand-effect-scope";
import { useLiveQuery } from "@/shared/lib/use-live-query";
import type { TerminalCancel, TerminalPorts, TerminalStart } from "./contracts";
import { runTerminalJob } from "./run-job";
import { useJobHistory } from "./use-job-history";
export interface TerminalWorkspaceContext {
  context: VerifiedPlatformContext;
  selectedProjectId: string | null;
}
function terminalProjectAllowed(resources: HandEffectScope[]): boolean {
  return ["terminal_status", "workspace_create", "job_start", "job_read", "job_cancel"].every(
    (tool) =>
      resources.some(
        (scope) =>
          scope.hand === "terminal" && scope.tool === tool && scope.action === "terminal.execute",
      ),
  );
}
export function useTerminalWorkspace(props: TerminalWorkspaceContext, port: TerminalPorts) {
  const resources = ref<HandEffectScope[]>([]);
  const command = ref(""),
    output = ref(""),
    notice = ref(""),
    busy = ref(false);
  const project = computed(() =>
    props.context.projects.find((p) => p.id === props.selectedProjectId),
  );
  const allowed = computed(
    () =>
      !!project.value?.permissions.includes("use_resources") &&
      terminalProjectAllowed(resources.value),
  );
  let controller: AbortController | null = null,
    generation = 0;
  let pending: TerminalStart | null = null;
  const pendingCommand = ref(false);
  const activeJob = ref("");
  const identityKey = computed(() =>
    JSON.stringify([
      props.context.rauthy.issuer,
      props.context.rauthy.subject,
      props.context.user.id,
      props.selectedProjectId,
    ]),
  );
  const storageKey = computed(() => "briareus-human-terminal-intent:" + identityKey.value);
  const historyAvailable = computed(
    () =>
      !!port.history &&
      allowed.value &&
      resources.value.some(
        (scope) =>
          scope.tool === "job_list" &&
          scope.hand === "terminal" &&
          scope.action === "terminal.execute",
      ),
  );
  const { jobs, jobsLoading, jobsNotice, historyLoaded, refreshJobs } = useJobHistory(
    {
      project: () => project.value?.id ?? null,
      identity: () => identityKey.value,
      enabled: () => historyAvailable.value,
    },
    port.history,
  );
  function explain(code: string): string {
    if (code.includes("PERMISSION") || code.includes("HTTP_403"))
      return "Нет доступа к терминалу этого проекта. Обновите страницу или проверьте свои права в проекте.";
    if (code.includes("REVISION") || code.includes("CONFLICT"))
      return "Доступ к проекту изменился. Обновите подключение.";
    if (code.includes("SCOPE") || code.includes("INVALID"))
      return "Сервер не подтвердил выбранный ресурс или параметры. Обновите подключение.";
    if (code.includes("OUTCOME") || code.includes("UNCERTAIN"))
      return "Результат операции пока не подтверждён.";
    return "Исполнитель этого проекта недоступен. Обновите подключение или выберите другой проект.";
  }
  async function load(): Promise<void> {
    if (!project.value || busy.value) return;
    controller?.abort();
    const request = new AbortController();
    controller = request;
    const run = ++generation,
      scope = project.value.id;
    notice.value = "";
    try {
      const found = await port.resources(scope, request.signal);
      if (run !== generation) return;
      resources.value = found;
    } catch (error) {
      if (run === generation) {
        resources.value = [];
        notice.value = explain(
          error instanceof Error ? error.message : "RUNTIME_OWNER_UNAVAILABLE",
        );
      }
    }
  }

  function prepareExecution(): TerminalStart | null {
    const scope = project.value;
    if (!scope || busy.value || !allowed.value || (!pending && !command.value.trim())) return null;
    if (!pending) {
      pending = {
        operation_uuid: crypto.randomUUID(),
        project_uuid: scope.id,
        tool: "job_start",
        arguments: { workspace_id: "default", command: command.value, interactive: false },
      };
      port.save(storageKey.value, pending);
      pendingCommand.value = true;
    }
    return pending;
  }
  function clearIntent(): void {
    pending = null;
    activeJob.value = "";
    pendingCommand.value = false;
    port.forget(storageKey.value);
  }
  function executionFailure(run: number, error: unknown): void {
    if (run === generation)
      notice.value =
        explain(error instanceof Error ? error.message : "TERMINAL_OUTCOME_UNKNOWN") +
        " Если идентификатор задания получен, можно продолжить чтение. Не повторяйте запуск с неподтверждённым результатом.";
  }
  async function execute(): Promise<void> {
    const recovering = pending !== null,
      intent = prepareExecution();
    if (!intent) return;
    busy.value = true;
    notice.value = "";
    const run = generation,
      request = new AbortController();
    controller = request;
    try {
      const result = await runTerminalJob(
        {
          intent,
          recovering,
          jobId: activeJob.value,
          signal: request.signal,
          current: () => run === generation && allowed.value,
          started: (id) => {
            activeJob.value = id;
            output.value = "";
            port.save(storageKey.value, intent, id);
          },
          output: (text) => {
            output.value = text;
          },
        },
        port.command,
      );
      if (run !== generation || result.kind === "superseded") return;
      notice.value = "Команда завершена: " + result.state;
      clearIntent();
    } catch (error) {
      executionFailure(run, error);
    } finally {
      if (run === generation) busy.value = false;
    }
  }

  async function cancelJob(): Promise<void> {
    if (!activeJob.value || !pending || !allowed.value) return;
    const run = generation;
    const intent: TerminalCancel = {
      ...pending,
      operation_uuid: crypto.randomUUID(),
      tool: "job_cancel",
      arguments: { job_id: activeJob.value, grace_seconds: 0.5 },
    };
    try {
      const result = await port.command(intent);
      if (result.kind === "failed" && run === generation)
        notice.value = "Не удалось подтвердить остановку задания.";
    } catch {
      if (run === generation) notice.value = "Результат остановки не подтверждён.";
    }
  }

  function newCommand(): void {
    if (busy.value) return;
    clearIntent();
    command.value = "";
    notice.value =
      "Исходный результат остаётся неподтверждённым. Новая команда создаст отдельную операцию.";
  }

  watch(
    identityKey,
    () => {
      controller?.abort();
      ++generation;
      busy.value = false;
      resources.value = [];
      output.value = "";
      command.value = "";
      pending = null;
      pendingCommand.value = false;
      activeJob.value = "";
      const saved = port.restore(storageKey.value, props.selectedProjectId);
      if (saved) {
        pending = saved.intent;
        command.value = saved.intent.arguments.command;
        pendingCommand.value = true;
        activeJob.value = saved.jobId;
      }
    },
    { immediate: true },
  );
  onBeforeUnmount(() => {
    controller?.abort();
    ++generation;
  });
  const liveQuery = useLiveQuery(load, {
    enabled: () => !!project.value,
    paused: () => busy.value,
    topics: ["management.events"],
    accept: (event) => eventProjectId(event) === props.selectedProjectId,
  });
  watch(identityKey, () => liveQuery.invalidate());
  return {
    jobs,
    jobsLoading,
    jobsNotice,
    historyAvailable,
    historyLoaded,
    refreshJobs,
    resources,
    command,
    output,
    notice,
    busy,
    project,
    allowed,
    pendingCommand,
    activeJob,
    execute,
    cancelJob,
    newCommand,
  };
}
