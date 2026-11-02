import { eventProjectId } from "@/shared/events";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import type { VerifiedPlatformContext } from "@/entities/workspace";
import { useProofLifetime } from "@/shared/lib/lifetime";
import { useLiveQuery } from "@/shared/lib/use-live-query";
import { requestConnection } from "../api/connections";
import { catalogScopeFingerprint, hasCurrentProject } from "./catalog-metadata";
import type { ConnectionProvider } from "./connection-draft";
import type {
  Connection,
  ConnectionCommand,
  ConnectionSubmit,
  ConnectionSubmission,
} from "./connection-contracts";
import {
  parseConnectionDeleted,
  parseConnectionForms,
  parseConnectionPage,
  parseConnectionProbe,
  parseConnectionSubmission,
} from "./connection-response";
import { ConnectionPages } from "./connection-pages";

interface ConnectionScope {
  context: () => VerifiedPlatformContext;
  project: () => string | null;
}
export function useConnections(scope: ConnectionScope) {
  const live = useProofLifetime(() => scope.context().expires_at);
  const ready = computed(() => {
    const context = scope.context(),
      project = scope.project();
    return Boolean(
      project &&
        live.value &&
        context.user.role === "operator" &&
        hasCurrentProject(context, project),
    );
  });
  const fingerprint = computed(() => catalogScopeFingerprint(scope.context(), scope.project()));
  const rows = ref<Connection[]>([]),
    busy = ref(false),
    message = ref("");
  const acceptedProviders = ref<ConnectionProvider[]>([]);
  const schemaReady = computed(() => acceptedProviders.value.length > 0);
  const checks = ref<Record<string, string>>({}),
    editing = ref<ConnectionProvider | null>(null);
  const deleting = ref<string | null>(null),
    editingRow = ref<Connection | null>(null);
  const deleteTarget = ref<Connection | null>(null);
  let controller: AbortController | null = null,
    epoch = 0,
    createId = crypto.randomUUID();
  let disposed = false;
  function reset(): void {
    ++epoch;
    controller?.abort();
    controller = null;
    busy.value = false;
    rows.value = [];
    checks.value = {};
    editing.value = null;
    editingRow.value = null;
    deleting.value = null;
    acceptedProviders.value = [];
    message.value = "";
  }
  function current(run: number, authority: string, signal: AbortSignal): boolean {
    if (disposed || run !== epoch || authority !== fingerprint.value || !ready.value) return false;
    if (signal.aborted) {
      message.value = "Ответ не получен. Обновите список, чтобы уточнить результат";
      return false;
    }
    return true;
  }
  async function request<T>(
    command: ConnectionCommand,
    parse: (value: unknown) => T | null,
  ): Promise<T | null> {
    const project = scope.project();
    if (disposed || !ready.value || busy.value || !project) return null;
    busy.value = true;
    message.value = "";
    const run = epoch,
      authority = fingerprint.value,
      abort = new AbortController();
    controller = abort;
    const timeout = setTimeout(() => abort.abort(), 18_000);
    try {
      const result = await requestConnection(command, project, abort.signal, parse);
      if (!current(run, authority, abort.signal)) return null;
      if (result.kind === "failed") {
        message.value = result.message;
        return null;
      }
      return result.value;
    } finally {
      clearTimeout(timeout);
      if (run === epoch) {
        busy.value = false;
        controller = null;
      }
    }
  }
  async function reload(): Promise<void> {
    const run = epoch,
      pages = new ConnectionPages();
    let cursor: string | undefined;
    do {
      const result = await request(
        { action: "list", ...(cursor ? { cursor } : {}) },
        parseConnectionPage,
      );
      if (!result || run !== epoch) return;
      const next = pages.accept(result);
      if (next.kind === "complete") {
        rows.value = next.items;
        return;
      }
      if (next.kind === "invalid") {
        message.value = "Некорректная страница подключений";
        return;
      }
      cursor = next.cursor;
    } while (cursor);
  }
  async function load(): Promise<void> {
    const run = epoch;
    const schema = await request({ action: "forms" }, parseConnectionForms);
    if (run !== epoch) return;
    acceptedProviders.value = schema?.providers ?? [];
    if (schema) await reload();
  }
  function canEdit(provider: ConnectionProvider): boolean {
    return ready.value && acceptedProviders.value.includes(provider);
  }
  function open(provider: ConnectionProvider, row: Connection | null = null): void {
    if (!canEdit(provider) || busy.value) return;
    message.value = "";
    createId = crypto.randomUUID();
    editingRow.value = row;
    editing.value = provider;
  }
  const submit: ConnectionSubmit = async (action, configuration, credential) => {
    const provider = editing.value;
    if (!provider || !canEdit(provider) || configuration.provider !== provider) return null;
    const id = editingRow.value?.id ?? createId;
    const command: ConnectionCommand = {
      action: action === "create" && editingRow.value ? "update" : action,
      configuration,
      credential,
      connection_uuid: id,
      expected_revision: editingRow.value?.revision ?? null,
      alias: `${configuration.provider}-${createId.slice(0, 8)}`,
    };
    const result = await request<ConnectionSubmission>(command, (value) => {
      if (action === "verify") return parseConnectionProbe(value);
      const saved = parseConnectionSubmission(value);
      return saved && "item" in saved && saved.item.id === id && saved.item.provider === provider
        ? saved
        : null;
    });
    if (result && "status" in result && result.status !== "connected")
      message.value =
        result.status === "denied"
          ? "Провайдер отклонил учётные данные или доступ"
          : "Не удалось подтвердить подключение к сервису";
    return result;
  };
  async function saved(): Promise<void> {
    editing.value = null;
    editingRow.value = null;
    await reload();
  }
  async function check(row: Connection): Promise<void> {
    const result = await request(
      { action: "check", connection_uuid: row.id },
      parseConnectionProbe,
    );
    if (!result) return;
    checks.value[row.id] =
      result.status === "connected"
        ? `Подключено${result.identity ? ` · ${result.identity}` : ""}`
        : result.status === "denied"
          ? "Доступ отклонён"
          : "Подключение не подтверждено";
  }
  async function remove(row: Connection): Promise<void> {
    if (deleteTarget.value?.id !== row.id || deleteTarget.value.revision !== row.revision) return;
    const result = await request(
      { action: "delete", connection_uuid: row.id, expected_revision: row.revision },
      parseConnectionDeleted,
    );
    if (result) {
      deleting.value = null;
      delete checks.value[row.id];
      await reload();
    }
  }
  watch(
    deleting,
    (id) => {
      deleteTarget.value = rows.value.find((row) => row.id === id) ?? null;
    },
    { flush: "sync" },
  );
  watch(
    rows,
    (currentRows) => {
      const target = deleteTarget.value;
      if (
        target &&
        !currentRows.some((row) => row.id === target.id && row.revision === target.revision)
      )
        deleting.value = null;
    },
    { flush: "sync" },
  );
  watch([fingerprint, ready], reset, { immediate: true, flush: "sync" });
  const liveQuery = useLiveQuery(load, {
    enabled: () => ready.value,
    paused: () => busy.value,
    topics: ["management.events"],
    accept: (event) =>
      event.type.startsWith("connection.") && eventProjectId(event) === scope.project(),
  });
  watch(fingerprint, () => liveQuery.invalidate());
  onBeforeUnmount(() => {
    disposed = true;
    reset();
  });
  return {
    live,
    ready,
    rows,
    busy,
    message,
    schemaReady,
    checks,
    editing,
    deleting,
    editingRow,
    deleteTarget,
    canEdit,
    open,
    submit,
    saved,
    check,
    remove,
  };
}
