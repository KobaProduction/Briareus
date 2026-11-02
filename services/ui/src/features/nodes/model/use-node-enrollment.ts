import { onMounted, ref } from "vue";
import type { ManagedNode } from "@/entities/node";
import { useNodeScope } from "./use-node-scope";
import type { NodeGateway } from "./node-commands";
export function useNodeEnrollment(
  props: { node: ManagedNode; projectId: string; action: "setup" | "pair" | "enable" },
  gateway: NodeGateway,
  notifications: { changed: () => void; close: () => void },
) {
  const busy = ref(false),
    error = ref(""),
    publicKey = ref(""),
    setup = ref("");
  let operation = crypto.randomUUID();
  const owner = useNodeScope(
    () => JSON.stringify([props.projectId, props.node.id, props.node.sequence, props.action]),
    () => {
      busy.value = false;
      error.value = "";
      publicKey.value = "";
      setup.value = "";
      operation = crypto.randomUUID();
    },
  );
  function command<Action extends "setup" | "enable" | "pair">(action: Action) {
    return {
      operation_uuid: operation,
      action,
      node_uuid: props.node.id,
      expected_sequence: props.node.sequence,
    };
  }
  async function showSetup() {
    const run = owner.capture();
    if (busy.value) return;
    busy.value = true;
    error.value = "";
    operation = crypto.randomUUID();
    try {
      const result = await gateway.setup(props.projectId, props.node, operation);
      if (owner.current(run)) setup.value = JSON.stringify(result.setup, null, 2);
    } catch {
      if (owner.current(run)) error.value = "Не удалось получить параметры установки.";
    } finally {
      if (owner.current(run)) busy.value = false;
    }
  }
  async function pair() {
    const run = owner.capture();
    if (busy.value) return;
    busy.value = true;
    error.value = "";
    try {
      await gateway.command(props.projectId, {
        ...command("pair"),
        public_key: publicKey.value.trim() + "\n",
      });
      if (!owner.current(run)) return;
      notifications.changed();
      notifications.close();
    } catch {
      if (owner.current(run))
        error.value =
          "Подключение не подтверждено. Проверьте публичный ключ, адрес и разрешение адреса в Core. Изменённые параметры требуют новой операции.";
    } finally {
      if (owner.current(run)) busy.value = false;
    }
  }
  async function enable() {
    const run = owner.capture();
    if (busy.value) return;
    busy.value = true;
    error.value = "";
    operation = crypto.randomUUID();
    try {
      await gateway.command(props.projectId, command("enable"));
      if (!owner.current(run)) return;
      notifications.changed();
      notifications.close();
    } catch {
      if (owner.current(run))
        error.value =
          "Включение не подтверждено. Проверьте состояние ноды перед повторной командой.";
    } finally {
      if (owner.current(run)) busy.value = false;
    }
  }
  onMounted(() => {
    if (props.action === "setup") void showSetup();
  });

  return { busy, error, publicKey, setup, showSetup, pair, enable };
}
