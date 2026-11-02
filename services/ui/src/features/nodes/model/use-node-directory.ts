import { computed, onScopeDispose, ref, watch } from "vue";
import type { ManagedNode } from "@/entities/node";
import {
  DEFAULT_NODE_LIMITS,
  MEBIBYTE,
  NODE_RESERVED_LIMITS,
  nodeBudgetAllowed,
} from "@/entities/node";
import type { VerifiedPlatformContext } from "@/entities/workspace";
import { useLiveQuery } from "@/shared/lib/use-live-query";
import { isUuid4 } from "@/shared/lib/uuid";
import { useNodeScope } from "./use-node-scope";
import type { NodeGateway, NodeCommand } from "./node-commands";

export function useNodeDirectory(
  props: { context: VerifiedPlatformContext; projectId: string | null },
  gateway: NodeGateway,
) {
  const project = computed(
    () =>
      props.context.projects.find(
        (item) => item.id === props.projectId && item.permissions.includes("use_resources"),
      ) ?? props.context.projects.find((item) => item.permissions.includes("use_resources")),
  );
  const operator = computed(() => props.context.user.role === "operator");
  const rows = ref<ManagedNode[]>([]),
    error = ref(""),
    loading = ref(false),
    busy = ref(false);
  const editor = ref<"register" | "rename" | "budget" | null>(null),
    target = ref<ManagedNode | null>(null),
    disable = ref<ManagedNode | null>(null);
  const enrollment = ref<{ node: ManagedNode; action: "setup" | "pair" | "enable" } | null>(null);
  const catalog = ref(false);
  const placementNode = ref<ManagedNode | null>(null);
  const name = ref(""),
    endpoint = ref(""),
    hostUuid = ref(""),
    runtimeUid = ref("2201"),
    memoryMb = ref("2048"),
    cpuMillis = ref("2000"),
    pids = ref("512");
  const scope = ref<"personal" | "team" | "shared">("shared"),
    formError = ref("");
  let disposed = false,
    readVersion = 0,
    operation = crypto.randomUUID(),
    nodeId = crypto.randomUUID();
  onScopeDispose(() => {
    disposed = true;
    readVersion++;
  });
  watch([() => props.context.user.id, () => project.value?.id], () => {
    rows.value = [];
    editor.value = null;
    disable.value = null;
    enrollment.value = null;
    readVersion++;
  });
  const owner = useNodeScope(
    () => JSON.stringify([props.context.user.id, project.value?.id]),
    () => {
      busy.value = false;
      placementNode.value = null;
      catalog.value = false;
    },
  );
  function currentRead(version: number): boolean {
    return !disposed && version === readVersion;
  }
  async function read() {
    const id = project.value?.id,
      version = ++readVersion;
    if (!id || !operator.value) return;
    loading.value = true;
    try {
      const result = await gateway.inventory(id);
      if (currentRead(version)) {
        rows.value = result;
        error.value = "";
      }
    } catch {
      if (currentRead(version))
        error.value = "Не удалось получить ноды. Проверьте доступность Resources.";
    } finally {
      if (currentRead(version)) loading.value = false;
    }
  }
  const live = useLiveQuery(read, {
    enabled: () => operator.value && !!project.value,
    topics: ["management.events"],
    accept: (event) => event.type.startsWith("node."),
  });
  watch(
    () => project.value?.id,
    () => live.invalidate(),
  );
  function open(kind: "register" | "rename" | "budget", node?: ManagedNode) {
    editor.value = kind;
    target.value = node ?? null;
    name.value = node?.name ?? "";
    formError.value = "";
    memoryMb.value = String(
      (node?.budget.total.memory_bytes ?? DEFAULT_NODE_LIMITS.memory_bytes) / MEBIBYTE,
    );
    cpuMillis.value = String(node?.budget.total.cpu_millis ?? DEFAULT_NODE_LIMITS.cpu_millis);
    pids.value = String(node?.budget.total.pids ?? DEFAULT_NODE_LIMITS.pids);
    operation = crypto.randomUUID();
    nodeId = crypto.randomUUID();
  }
  function openDisable(node: ManagedNode) {
    disable.value = node;
    operation = crypto.randomUUID();
  }
  const budgetLimits = computed(() => ({
    memory_bytes: Number(memoryMb.value) * MEBIBYTE,
    cpu_millis: Number(cpuMillis.value),
    pids: Number(pids.value),
  }));
  const budgetValid = computed(() => nodeBudgetAllowed(budgetLimits.value));
  const valid = computed(() =>
    editor.value === "budget"
      ? budgetValid.value
      : !!name.value.trim() &&
        (editor.value === "rename" ||
          (/^https:\/\/[a-z0-9.-]+\/?$/.test(endpoint.value) &&
            isUuid4(hostUuid.value) &&
            Number.isInteger(Number(runtimeUid.value)) &&
            Number(runtimeUid.value) >= 2000 &&
            budgetValid.value &&
            (scope.value !== "team" || project.value?.owner.kind === "team"))),
  );
  function selectedBudget() {
    return {
      total: budgetLimits.value,
      reserved: target.value?.budget.reserved ?? { ...NODE_RESERVED_LIMITS },
    };
  }
  function registrationOwner(): string | null {
    if (scope.value === "shared") return null;
    if (scope.value === "personal") return props.context.user.id;
    return project.value?.owner.id ?? null;
  }
  function editorCommand(): NodeCommand {
    if (!project.value) throw Error("PROJECT_REQUIRED");
    let command: NodeCommand;
    if (editor.value === "budget" && target.value)
      command = {
        operation_uuid: operation,
        action: "budget",
        node_uuid: target.value.id,
        expected_sequence: target.value.sequence,
        budget: selectedBudget(),
      };
    else if (editor.value === "rename" && target.value)
      command = {
        operation_uuid: operation,
        action: "rename",
        node_uuid: target.value.id,
        name: name.value.trim(),
        expected_sequence: target.value.sequence,
      };
    else
      command = {
        operation_uuid: operation,
        action: "register",
        registration: {
          id: nodeId,
          name: name.value.trim(),
          scope: scope.value,
          owner_uuid: registrationOwner(),
          host_uuid: hostUuid.value,
          runtime_uid: Number(runtimeUid.value),
          endpoint: endpoint.value,
          budget: selectedBudget(),
        },
      };
    return command;
  }
  async function save() {
    const run = owner.capture();
    if (!project.value || busy.value || !valid.value) return;
    busy.value = true;
    formError.value = "";
    try {
      const command = editorCommand();
      await gateway.command(project.value.id, command);
      if (!owner.current(run)) return;
      editor.value = null;
      live.invalidate();
    } catch {
      if (!owner.current(run)) return;
      formError.value =
        "Операция не подтверждена. Запись могла сохраниться; проверьте список. Изменённые параметры отправляйте новой операцией.";
    } finally {
      if (owner.current(run)) busy.value = false;
    }
  }
  async function confirmDisable() {
    const run = owner.capture();
    if (!project.value || !disable.value || busy.value) return;
    busy.value = true;
    try {
      await gateway.command(project.value.id, {
        operation_uuid: operation,
        action: "disable",
        node_uuid: disable.value.id,
        expected_sequence: disable.value.sequence,
      });
      if (!owner.current(run)) return;
      disable.value = null;
      live.invalidate();
    } catch {
      if (!owner.current(run)) return;
      error.value = "Отключение не подтверждено сервером. Проверьте состояние ноды.";
    } finally {
      if (owner.current(run)) busy.value = false;
    }
  }
  const scopeName = (value: string) =>
    ({ personal: "Личная", team: "Командная", shared: "Общая" })[value] ?? value;

  return {
    project,
    operator,
    rows,
    error,
    loading,
    busy,
    editor,
    target,
    disable,
    enrollment,
    catalog,
    placementNode,
    name,
    endpoint,
    hostUuid,
    runtimeUid,
    memoryMb,
    cpuMillis,
    pids,
    scope,
    formError,
    budgetValid,
    valid,
    open,
    openDisable,
    save,
    confirmDisable,
    scopeName,
    refresh:live.invalidate,
  };
}
