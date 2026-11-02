import { computed, onScopeDispose, ref, watch } from "vue";
import type { VerifiedPlatformContext } from "@/entities/workspace";
import { useLiveQuery } from "@/shared/lib/use-live-query";
import {
  readAgentDirectory,
  type AgentDirectoryPort,
  type DirectoryAgent,
} from "./agent-directory";
interface AgentDirectoryOptions {
  context: VerifiedPlatformContext;
  projectId: string | null;
}
export function useAgentDirectory(props: AgentDirectoryOptions, port: AgentDirectoryPort) {
  const rows = ref<DirectoryAgent[]>([]),
    selected = ref<DirectoryAgent | null>(null),
    loading = ref(false),
    error = ref("");
  let generation = 0,
    disposed = false,
    controller = new AbortController(),
    detail: AbortController | null = null;
  const project = computed(() =>
    props.context.projects.find((item) => item.id === props.projectId),
  );
  const readable = computed(() => !!project.value?.permissions.includes("use_resources"));
  const ownerKey = computed(() =>
    JSON.stringify([
      props.context.user.id,
      props.context.rauthy.issuer,
      props.context.rauthy.subject,
      props.projectId,
      readable.value,
    ]),
  );
  const current = (run: number): boolean =>
    !disposed && run === generation && !controller.signal.aborted;
  function currentProof(): boolean {
    return readable.value && Date.parse(props.context.expires_at) > Date.now();
  }
  function acceptDirectory(result: DirectoryAgent[]): void {
    rows.value = result;
    const selectedId = selected.value?.id;
    if (selectedId && !result.some((agent) => agent.id === selectedId)) selected.value = null;
  }
  async function load(): Promise<void> {
    if (!props.projectId || !currentProof()) return;
    const run = generation,
      id = props.projectId,
      signal = controller.signal;
    loading.value = true;
    error.value = "";
    try {
      const result = await readAgentDirectory(
        port,
        id,
        signal,
        () => current(run) && currentProof(),
      );
      if (!result || !current(run)) return;
      acceptDirectory(result);
    } catch {
      if (current(run)) error.value = "Не удалось получить агентов выбранного проекта.";
    } finally {
      if (current(run)) loading.value = false;
    }
  }
  async function open(row: DirectoryAgent): Promise<void> {
    if (!props.projectId || row.project_uuid !== props.projectId || !currentProof()) return;
    const run = generation,
      id = props.projectId,
      request = new AbortController();
    detail?.abort();
    detail = request;
    const signal = AbortSignal.any([controller.signal, request.signal]);
    try {
      const result = await port.get(id, row.id, signal);
      if (current(run) && detail === request && !signal.aborted && currentProof())
        selected.value = result;
    } catch {
      if (current(run) && detail === request && !signal.aborted)
        error.value = "Не удалось получить выбранного агента.";
    } finally {
      if (detail === request) detail = null;
    }
  }
  const live = useLiveQuery(load, {
    enabled: () => readable.value,
    topics: ["management.events"],
    accept: (event) => event.type.startsWith("agent."),
  });
  watch(
    ownerKey,
    () => {
      generation++;
      controller.abort();
      detail?.abort();
      detail = null;
      controller = new AbortController();
      rows.value = [];
      selected.value = null;
      loading.value = false;
      error.value = "";
      live.invalidate();
    },
    { flush: "sync" },
  );
  onScopeDispose(() => {
    disposed = true;
    generation++;
    controller.abort();
    detail?.abort();
  });
  return { rows, selected, loading, error, project, open };
}
