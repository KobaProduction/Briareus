import { computed, ref } from "vue";
import type { NodeRuntimePolicy as Policy } from "./node-replies";
import { useNodeScope } from "./use-node-scope";
import { validRuntimePolicyValue, runtimePolicyValue } from "./runtime-policy-value";
import type {
  NodeGateway,
  RuntimePolicyKey,
  RuntimePolicyValues,
  RuntimePolicyWrite,
} from "./node-commands";
export function useRuntimePolicy(
  props: { projectId: string; nodeId: string },
  gateway: NodeGateway,
) {
  type Key = RuntimePolicyKey;
  const fields: { key: Key; label: string; unit: string }[] = [
    { key: "execution_timeout_seconds", label: "Таймаут выполнения MCP", unit: "секунд" },
    { key: "web_max_tabs", label: "Максимум вкладок браузера", unit: "вкладок" },
    { key: "web_tab_idle_seconds", label: "Закрывать неактивные вкладки через", unit: "секунд" },
    {
      key: "terminal_idle_seconds",
      label: "Завершать неактивные сеансы Terminal через",
      unit: "секунд",
    },
  ];
  const open = ref(false),
    scope = ref<"server" | "node">("node"),
    busy = ref(false),
    error = ref(""),
    policy = ref<Policy | null>(null);
  const modes = ref<Partial<Record<Key, "inherit" | "none" | "value">>>({}),
    values = ref<Partial<Record<Key, string>>>({});
  let operation = crypto.randomUUID();
  const submitted = ref<RuntimePolicyWrite | null>(null);
  const owner = useNodeScope(
    () => JSON.stringify([props.projectId, props.nodeId, scope.value]),
    () => {
      policy.value = null;
      submitted.value = null;
      busy.value = false;
      error.value = "";
      operation = crypto.randomUUID();
    },
  );
  const valid = computed(
    () =>
      !!policy.value &&
      fields.every(
        (f) =>
          modes.value[f.key] === "inherit" ||
          modes.value[f.key] === "none" ||
          (modes.value[f.key] === "value" && validRuntimePolicyValue(values.value[f.key], f.key)),
      ),
  );
  async function load() {
    const run = owner.capture();
    busy.value = true;
    error.value = "";
    policy.value = null;
    submitted.value = null;
    operation = crypto.randomUUID();
    try {
      const result = await gateway.runtimePolicy(props.projectId, scope.value, props.nodeId);
      if (!owner.current(run)) return;
      policy.value = result.runtime_policy;
      applyPolicy(policy.value);
    } catch {
      if (owner.current(run)) error.value = "Не удалось получить настройки выполнения.";
    } finally {
      if (owner.current(run)) busy.value = false;
    }
  }
  async function show() {
    open.value = true;
    await load();
  }
  function retryCommand(current: Policy): RuntimePolicyWrite {
    if (submitted.value) return submitted.value;
    const command: RuntimePolicyWrite = {
      operation_uuid: operation,
      action: "runtime_policy",
      policy_scope: scope.value,
      node_uuid: scope.value === "node" ? props.nodeId : null,
      policy_values: policyOverrides(),
      expected_policy_sequence: current.sequence,
    };
    submitted.value = command;
    return command;
  }
  async function save(): Promise<void> {
    if (!policy.value || !valid.value || busy.value) return;
    const run = owner.capture(),
      command = retryCommand(policy.value);
    busy.value = true;
    error.value = "";
    try {
      await gateway.command(props.projectId, command);
      if (owner.current(run)) open.value = false;
    } catch {
      if (owner.current(run))
        error.value = "Сохранение не подтверждено. Повтор использует ту же операцию.";
    } finally {
      if (owner.current(run)) busy.value = false;
    }
  }

  function applyPolicy(current: Policy): void {
    for (const field of fields) {
      const value = current.overrides[field.key];
      modes.value[field.key] = value === undefined ? "inherit" : value === null ? "none" : "value";
      values.value[field.key] = String(value ?? current.effective[field.key] ?? "");
    }
  }
  function policyOverrides(): RuntimePolicyValues {
    const overrides: RuntimePolicyValues = {};
    for (const field of fields) {
      const mode = modes.value[field.key];
      if (mode !== "inherit")
        overrides[field.key] =
          mode === "none" ? null : runtimePolicyValue(values.value[field.key], field.key);
    }
    return overrides;
  }
  return {
    open,
    scope,
    busy,
    error,
    policy,
    modes,
    values,
    submitted,
    valid,
    fields,
    load,
    show,
    save,
  };
}
