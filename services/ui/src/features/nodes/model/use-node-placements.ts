import { computed, ref, watch } from "vue";
import type { ManagedNode, ModuleCatalog } from "@/entities/node";
import { MINIMUM_MODULE_LIMITS, resourceAllocationAllowed } from "@/entities/node";
import { useLiveQuery } from "@/shared/lib/use-live-query";
import type { ModuleConfiguration } from "./module-configuration";
import {
  configurationValid,
  defaultConfiguration,
  initialConfiguration,
} from "./module-configuration";
import { operationInProgress } from "./operation-presentation";
import { currentPlacementRelease, placementHasChanges } from "./placement-edit";
import type { ProjectWorkspace, ProjectWorkspaceMount } from "./project-workspace";
import { placementMutation, placementRecoveryAllowed, type Placement } from "./placement-intent";
import { createRecoveryIntents, type RecoveryIntentStorage } from "./recovery-intents";
import { useNodeScope } from "./use-node-scope";
import type { NodeGateway } from "./node-commands";

export function useNodePlacements(
  props: { node: ManagedNode; projectId: string },
  gateway: NodeGateway,
  recoveryStorage: RecoveryIntentStorage,
) {
  const rows = ref<Placement[]>([]),
    catalog = ref<ModuleCatalog>({ modules: [], artifacts: [], releases: [] });
  const loading = ref(false),
    busy = ref(false),
    error = ref(""),
    formError = ref(""),
    editor = ref(false),
    recovering = ref<string | null>(null);
  const name = ref("Файлы проекта"),
    release = ref(""),
    memory = ref("128"),
    cpu = ref("100"),
    pids = ref("32");
  const updating = ref<Placement | null>(null);
  const configuration = ref<ModuleConfiguration>({});
  const workspaces = ref<ProjectWorkspace[]>([]),
    projectWorkspace = ref<ProjectWorkspaceMount | null>(null),
    workspaceBusy = ref(false),
    workspaceError = ref("");
  let workspaceOperation = crypto.randomUUID();
  let operation = crypto.randomUUID(),
    placementId = crypto.randomUUID(),
    submittedIntent: string | null = null;
  const scope = useNodeScope(
    () => JSON.stringify([props.projectId, props.node.id]),
    () => {
      rows.value = [];
      catalog.value = { modules: [], artifacts: [], releases: [] };
      workspaces.value = [];
      editor.value = false;
      updating.value = null;
      submittedIntent = null;
      busy.value = false;
      workspaceBusy.value = false;
      loading.value = false;
      recovering.value = null;
      workspaceOperation = crypto.randomUUID();
      operation = crypto.randomUUID();
      placementId = crypto.randomUUID();
      live.invalidate();
    },
  );
  async function read() {
    const run = scope.capture();
    loading.value = true;
    try {
      const results = await Promise.all([
        gateway.placements(props.projectId, props.node.id),
        gateway.catalog(props.projectId),
      ]);
      if (!scope.current(run)) return;
      if (scope.current(run)) {
        rows.value = results[0].items;
        catalog.value = results[1];
        error.value = "";
      }
      await readWorkspaces();
    } catch {
      if (scope.current(run)) error.value = "Не удалось получить MCP выбранного проекта на ноде.";
    } finally {
      if (scope.current(run)) loading.value = false;
    }
  }
  async function readWorkspaces() {
    const run = scope.capture();
    workspaceBusy.value = true;
    try {
      const result = await gateway.workspaces(props.projectId, props.node.id);
      if (scope.current(run)) {
        workspaces.value = result.items;
        workspaceError.value = "";
      }
    } catch {
      if (scope.current(run)) workspaceError.value = "Не удалось получить рабочую папку проекта.";
    } finally {
      if (scope.current(run)) workspaceBusy.value = false;
    }
  }
  async function ensureWorkspace() {
    const run = scope.capture();
    if (workspaceBusy.value || busy.value) return;
    workspaceBusy.value = true;
    workspaceError.value = "";
    try {
      const result = await gateway.ensureWorkspace(
        props.projectId,
        props.node.id,
        workspaceOperation,
      );
      if (scope.current(run)) {
        workspaces.value = [result.item];
        projectWorkspace.value = { id: result.item.id, read_only: false };
        workspaceOperation = crypto.randomUUID();
      }
    } catch {
      if (scope.current(run))
        workspaceError.value = "Создание папки не подтверждено. Повтор использует ту же операцию.";
    } finally {
      if (scope.current(run)) workspaceBusy.value = false;
    }
  }
  const live = useLiveQuery(read, {
    enabled: () => !!props.projectId,
    topics: ["management.events"],
    accept: (event) =>
      event.type === "node.modules" ||
      event.type === "node.runtime_policy" ||
      event.type.startsWith("node.module."),
  });
  const releases = computed(() =>
    catalog.value.releases.filter(
      (row) =>
        catalog.value.modules.some((module) => module.components.includes(row.module)) &&
        catalog.value.artifacts.some((item) => item.key === row.module && item.node_adapter) &&
        (!updating.value || row.module === updating.value.module),
    ),
  );
  const artifact = computed(() =>
    catalog.value.artifacts.find(
      (item) => item.key === releases.value.find((row) => row.id === release.value)?.module,
    ),
  );
  const selectedModule = computed(() => artifact.value?.key ?? updating.value?.module ?? "");
  const releaseSections = computed(() =>
    catalog.value.modules
      .map((section) => ({
        id: section.key,
        name: section.name,
        releases: releases.value.filter((row) => section.components.includes(row.module)),
      }))
      .filter((section) => section.releases.length),
  );
  watch(selectedModule, (module) => {
    if (!updating.value) {
      configuration.value = defaultConfiguration(module);
      projectWorkspace.value = null;
    }
  });
  function applyReleaseDefaults() {
    if (!artifact.value) return;
    if (updating.value) {
      const minimum = artifact.value.minimum_limits;
      memory.value = String(Math.max(Number(memory.value), minimum.memory_bytes / 1024 ** 2));
      cpu.value = String(Math.max(Number(cpu.value), minimum.cpu_millis));
      pids.value = String(Math.max(Number(pids.value), minimum.pids));
    } else if (artifact.value.default_limits) {
      const limits = artifact.value.default_limits;
      memory.value = String(limits.memory_bytes / 1024 ** 2);
      cpu.value = String(limits.cpu_millis);
      pids.value = String(limits.pids);
      if (!name.value.trim()) name.value = artifact.value.name;
    }
  }
  watch(release, applyReleaseDefaults);
  const valid = computed(
    () =>
      !!name.value.trim() &&
      releases.value.some((item) => item.id === release.value) &&
      (!["web", "reverse"].includes(selectedModule.value) || !workspaceBusy.value) &&
      resourceAllocationAllowed(
        editLimits.value,
        artifact.value?.minimum_limits ?? MINIMUM_MODULE_LIMITS,
        props.node.budget.total,
      ) &&
      configurationValid(selectedModule.value, configuration.value),
  );
  const editLimits = computed(() => ({
    memory_bytes: Number(memory.value) * 1024 ** 2,
    cpu_millis: Number(cpu.value),
    pids: Number(pids.value),
  }));
  const changed = computed(
    () =>
      !updating.value ||
      updating.value.runtime_policy_pending ||
      placementHasChanges(
        updating.value,
        release.value,
        releases.value,
        editLimits.value,
        configuration.value,
        projectWorkspace.value,
      ),
  );
  function open() {
    submittedIntent = null;
    updating.value = null;
    projectWorkspace.value = null;
    name.value = "";
    operation = crypto.randomUUID();
    placementId = crypto.randomUUID();
    release.value = releases.value[0]?.id ?? "";
    configuration.value = defaultConfiguration(
      releases.value.find((row) => row.id === release.value)?.module ?? "",
    );
    applyReleaseDefaults();
    formError.value = "";
    editor.value = true;
  }
  function openUpdate(row: Placement) {
    if (busy.value || operationInProgress(row.operation) || row.operation?.reconciliation_required)
      return;
    submittedIntent = null;
    updating.value = row;
    projectWorkspace.value = row.project_workspace ? { ...row.project_workspace } : null;
    operation = crypto.randomUUID();
    name.value = row.name;
    memory.value = String(row.limits.memory_bytes / 1024 ** 2);
    cpu.value = String(row.limits.cpu_millis);
    pids.value = String(row.limits.pids);
    release.value = currentPlacementRelease(row.release_uuid, releases.value);
    configuration.value = initialConfiguration(row.module, row.configuration);
    applyReleaseDefaults();
    formError.value = "";
    editor.value = true;
  }
  function canSubmitPlacement(): boolean {
    return !busy.value && valid.value && !!changed.value;
  }
  async function place() {
    const run = scope.capture();
    if (!canSubmitPlacement()) return;
    busy.value = true;
    formError.value = "";
    try {
      const module = placementMutation({
        updating: updating.value,
        module: selectedModule.value,
        configuration: configuration.value,
        workspace: projectWorkspace.value,
        limits: editLimits.value,
        release: release.value,
        placementId,
        nodeId: props.node.id,
        name: name.value,
      });
      const intent = JSON.stringify(module);
      if (submittedIntent !== null && submittedIntent !== intent) operation = crypto.randomUUID();
      submittedIntent = intent;
      await gateway.command(props.projectId, {
        operation_uuid: operation,
        action: "modules",
        module,
      });
      if (!scope.current(run)) return;
      editor.value = false;
      live.invalidate();
    } catch {
      if (!scope.current(run)) return;
      formError.value =
        "Запуск не подтверждён. Проверьте список операций: повтор сохранит идентификатор и не создаст второе размещение.";
    } finally {
      if (scope.current(run)) busy.value = false;
    }
  }
  const recoveryIntents = createRecoveryIntents(recoveryStorage, () => crypto.randomUUID());
  const recoveryKey = (id: string) =>
    `briareus-placement-recovery:${props.projectId}:${props.node.id}:${id}`;
  async function recover(row: Placement) {
    const run = scope.capture();
    if (!placementRecoveryAllowed(row, props.node.enabled, busy.value)) return;
    const key = recoveryKey(row.id),
      intent = recoveryIntents.acquire(key, row.sequence);
    busy.value = true;
    recovering.value = row.id;
    error.value = "";
    try {
      await gateway.command(props.projectId, {
        operation_uuid: intent.id,
        action: "modules",
        module: { action: "recover", recover: { id: row.id, expected_sequence: intent.sequence } },
      });
      recoveryIntents.complete(key);
      if (scope.current(run)) live.invalidate();
    } catch {
      if (!scope.current(run)) return;
      error.value =
        "Запуск сохранённой конфигурации не подтверждён. Повтор использует ту же операцию; сборка и параметры не меняются.";
      live.invalidate();
    } finally {
      if (scope.current(run)) {
        busy.value = false;
        recovering.value = null;
      }
    }
  }
  async function reconcile(row: Placement) {
    const run = scope.capture();
    if (!row.operation?.reconciliation_required || busy.value) return;
    busy.value = true;
    recovering.value = row.id;
    try {
      await gateway.command(props.projectId, {
        operation_uuid: crypto.randomUUID(),
        action: "modules",
        module: { action: "reconcile", target_operation_uuid: row.operation.id },
      });
      if (scope.current(run)) live.invalidate();
    } catch {
      if (!scope.current(run)) return;
      error.value = "Сверка с журналом ноды не подтверждена.";
    } finally {
      if (scope.current(run)) busy.value = false;
      if (scope.current(run)) recovering.value = null;
    }
  }

  return {
    rows,
    catalog,
    loading,
    busy,
    error,
    formError,
    editor,
    recovering,
    name,
    release,
    memory,
    cpu,
    pids,
    updating,
    configuration,
    workspaces,
    projectWorkspace,
    workspaceBusy,
    workspaceError,
    releases,
    artifact,
    selectedModule,
    releaseSections,
    valid,
    changed,
    open,
    openUpdate,
    place,
    recover,
    reconcile,
    ensureWorkspace,
  };
}
