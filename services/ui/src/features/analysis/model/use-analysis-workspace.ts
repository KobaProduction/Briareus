import { computed, onScopeDispose, ref, watch } from "vue";
import type { VerifiedPlatformContext } from "@/entities/workspace";
import { type ProjectCommandSource, RpcError } from "@/shared/events";
import type { HandEffectScope } from "@/shared/lib/hand-effect-scope";
import { completeMcpOperation, type McpOperation } from "@/shared/lib/transport";
import { useLiveQuery } from "@/shared/lib/use-live-query";
import { nativeAnalysisArguments, updateAnalysisArgument } from "../api/tool-results";
import type { AnalysisClient, AnalysisEngine, AnalysisInvocation } from "./command";
import { analysisOperationOutput } from "./operation-output";
import type { AnalysisRecoveryPort } from "./recovery";
import { preparationDelay, startAnalysis } from "./start-operation";
import type { AnalysisTool } from "./tool";

export interface AnalysisWorkspaceContext {
  context: VerifiedPlatformContext;
  selectedProjectId: string | null;
}
export interface AnalysisWorkspacePorts extends AnalysisRecoveryPort {
  resources(project: string, signal: AbortSignal): Promise<HandEffectScope[]>;
  client(source: ProjectCommandSource): AnalysisClient;
}
export function useAnalysisWorkspace(
  props: AnalysisWorkspaceContext,
  ports: AnalysisWorkspacePorts,
) {
  const scopes = ref<HandEffectScope[]>([]);
  const engine = ref<AnalysisEngine>("radare2"),
    catalog = ref<AnalysisTool[]>([]);
  const tool = ref(""),
    argumentsText = ref("{}"),
    output = ref(""),
    error = ref("");
  const busy = ref(false),
    operation = ref(""),
    filePath = ref(""),
    analysisProject = ref("");
  const selectedTool = computed(() => catalog.value.find((item) => item.name === tool.value));
  const projectArgument = computed(() =>
    ["project_id", "project_name", "project"].find((key) =>
      selectedTool.value?.inputProperties.includes(key),
    ),
  );
  const project = computed(() =>
    props.context.projects.find((item) => item.id === props.selectedProjectId),
  );
  const allowed = computed(
    () =>
      !!project.value?.permissions.includes("use_resources") &&
      ["analysis_tools", "analysis_start", "analysis_poll", "analysis_cancel"].every((name) =>
        scopes.value.some(
          (scope) =>
            scope.hand === "reverse" && scope.tool === name && scope.action === "analysis.import",
        ),
      ),
  );
  const identityKey = computed(() =>
    JSON.stringify([
      props.context.rauthy.issuer,
      props.context.rauthy.subject,
      props.context.user.id,
      props.selectedProjectId,
    ]),
  );
  const storageKey = computed(() => "briareus-human-analysis-operation:" + identityKey.value);
  let generation = 0,
    controller = new AbortController();
  const analysis = ports.client(() =>
    props.selectedProjectId && allowed.value
      ? {
          project_uuid: props.selectedProjectId,
          signal: controller.signal,
        }
      : null,
  );

  async function load(): Promise<void> {
    const selected = props.selectedProjectId;
    if (!selected || busy.value) return;
    const run = generation,
      signal = controller.signal;
    try {
      const found = await ports.resources(selected, signal);
      if (run !== generation || signal.aborted) return;
      scopes.value = found;
      if (!found.length) error.value = "Анализ проекта не подключён";
    } catch (failure) {
      if (run === generation) {
        scopes.value = [];
        error.value = String(failure);
      }
    }
  }
  async function tools(): Promise<void> {
    if (!allowed.value || busy.value || operation.value) return;
    busy.value = true;
    error.value = "";
    const run = generation,
      signal = controller.signal,
      selected = engine.value;
    try {
      const items = await startAnalysis({
        start: () => analysis.tools(selected),
        resolve: () => analysis.tools(selected),
        current: () => run === generation && !signal.aborted,
        preparing: () => {
          if (run === generation) output.value = "Анализатор подготавливается…";
        },
        wait: () => preparationDelay(signal),
      });
      if (run !== generation) return;
      catalog.value = items;
      tool.value = items[0]?.name ?? "";
      output.value = "";
    } catch (failure) {
      if (run === generation) error.value = String(failure);
    } finally {
      if (run === generation) busy.value = false;
    }
  }
  function rememberOperation(id: string): void {
    const selected = props.selectedProjectId;
    if (!selected) throw new Error("Выберите проект");
    ports.save(storageKey.value, selected, { engine: engine.value, operationId: id });
    operation.value = id;
  }
  function forgetOperation(): void {
    ports.forget(storageKey.value);
    operation.value = "";
  }
  function stopTracking(): void {
    if (busy.value) return;
    forgetOperation();
    output.value = "Отслеживание прекращено. Задание не отменяется.";
  }
  async function follow(
    initial: McpOperation<string>,
    run: number,
    signal: AbortSignal,
  ): Promise<void> {
    if (run !== generation || signal.aborted) return;
    rememberOperation(initial.operation_id);
    const result = await completeMcpOperation(initial, {
      current: () => run === generation && !signal.aborted,
      wait: () => preparationDelay(signal),
      poll: (id) => analysis.poll(id),
      progress: (value) => {
        if (run === generation) output.value = analysisOperationOutput(value);
      },
    });
    if (run === generation && result) {
      output.value = analysisOperationOutput(result);
      forgetOperation();
    }
  }
  function preparedInvocation(): AnalysisInvocation | null {
    try {
      nativeAnalysisArguments(argumentsText.value);
      return {
        engine: engine.value,
        tool: tool.value,
        argumentsText: argumentsText.value,
        projectArgument:
          projectArgument.value && analysisProject.value
            ? { name: projectArgument.value, value: analysisProject.value }
            : null,
      };
    } catch (failure) {
      error.value = String(failure);
      return null;
    }
  }
  function definiteStartRejection(failure: unknown): boolean {
    return (
      failure instanceof RpcError &&
      failure.uncertaintyDeclared &&
      !failure.uncertain &&
      failure.message !== "ANALYSIS_PREPARING"
    );
  }
  function startFailure(run: number, failure: unknown, rejected: boolean): void {
    if (run !== generation) return;
    error.value = String(failure);
    if (rejected) forgetOperation();
  }
  async function execute(): Promise<void> {
    if (!allowed.value || busy.value || operation.value) return;
    const invocation = preparedInvocation();
    if (!invocation) return;
    busy.value = true;
    error.value = "";
    const run = generation,
      signal = controller.signal,
      requestId = crypto.randomUUID();
    let rejectedBeforeDispatch = false;
    try {
      rememberOperation(`request:${requestId}`);
      const initial = await startAnalysis({
        start: async () => {
          try {
            return await analysis.start(invocation, requestId);
          } catch (failure) {
            rejectedBeforeDispatch = definiteStartRejection(failure);
            throw failure;
          }
        },
        resolve: () => analysis.poll(`request:${requestId}`),
        current: () => run === generation && !signal.aborted,
        preparing: () => {
          if (run === generation)
            output.value = "Анализатор подготавливается… Запуск ещё не отправлен.";
        },
        wait: () => preparationDelay(signal),
      });
      await follow(initial, run, signal);
    } catch (failure) {
      startFailure(run, failure, rejectedBeforeDispatch);
    } finally {
      if (run === generation) busy.value = false;
    }
  }
  async function resume(): Promise<void> {
    const selected = operation.value;
    if (!selected || busy.value || !allowed.value) return;
    const run = generation,
      signal = controller.signal;
    busy.value = true;
    error.value = "";
    try {
      await follow(await analysis.poll(selected), run, signal);
    } catch (failure) {
      if (run === generation) error.value = String(failure);
    } finally {
      if (run === generation) busy.value = false;
    }
  }
  async function cancel(): Promise<void> {
    if (!operation.value || !allowed.value) return;
    const run = generation;
    try {
      await analysis.cancel(operation.value);
      if (run === generation && !busy.value) await resume();
    } catch (failure) {
      if (run === generation) error.value = String(failure);
    }
  }
  function useFile(): void {
    try {
      const properties = selectedTool.value?.inputProperties ?? [];
      const key = ["workspace_path", "path", "file_path", "binary_path"].find((name) =>
        properties.includes(name),
      );
      if (!key)
        throw Error("У выбранного инструмента нет параметра пути. Выберите инструмент импорта.");
      argumentsText.value = updateAnalysisArgument(argumentsText.value, key, filePath.value);
    } catch (failure) {
      error.value = String(failure);
    }
  }
  function restoreContext(): void {
    generation++;
    controller.abort();
    controller = new AbortController();
    scopes.value = [];
    catalog.value = [];
    tool.value = "";
    argumentsText.value = "{}";
    filePath.value = "";
    analysisProject.value = "";
    operation.value = "";
    busy.value = false;
    output.value = "";
    error.value = "";
    const saved = ports.restore(storageKey.value, props.selectedProjectId);
    if (saved) {
      engine.value = saved.engine;
      operation.value = saved.operationId;
      output.value = "Сохранено отслеживание операции. Можно продолжить чтение результата.";
    }
  }
  restoreContext();
  watch(engine, () => {
    catalog.value = [];
    tool.value = "";
    argumentsText.value = "{}";
  });
  watch(tool, () => {
    argumentsText.value = "{}";
  });
  const live = useLiveQuery(load, {
    enabled: () => !!props.selectedProjectId,
    paused: () => busy.value,
    topics: ["management.events"],
  });
  watch(identityKey, () => {
    restoreContext();
    live.invalidate();
  });
  onScopeDispose(() => {
    generation++;
    controller.abort();
  });
  return {
    engine,
    catalog,
    tool,
    argumentsText,
    output,
    error,
    busy,
    operation,
    filePath,
    analysisProject,
    selectedTool,
    projectArgument,
    allowed,
    tools,
    execute,
    resume,
    cancel,
    useFile,
    stopTracking,
  };
}
