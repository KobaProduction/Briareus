import { computed, ref } from "vue";
import type { ModuleArtifact, ModuleImage, LogicalModule as CatalogModule } from "@/entities/node";
import { useLiveQuery } from "@/shared/lib/use-live-query";
import { useNodeScope } from "./use-node-scope";
import type { NodeGateway } from "./node-commands";
export function useModuleCatalog(props: { projectId: string }, gateway: NodeGateway) {
  const artifacts = ref<ModuleArtifact[]>([]),
    releases = ref<ModuleImage[]>([]),
    loading = ref(false),
    error = ref("");
  const modules = ref<CatalogModule[]>([]);
  const placements = ref<{ module: string; state: string }[]>([]);
  interface LogicalModule {
    id: string;
    name: string;
    modules: string[];
    components: ModuleArtifact[];
  }
  const details = ref<LogicalModule | null>(null);
  const publication = ref<ModuleArtifact | null>(null),
    busy = ref(false),
    formError = ref("");
  const commit = ref(""),
    fingerprint = ref(""),
    image = ref("");
  let operation = crypto.randomUUID(),
    releaseId = crypto.randomUUID();
  const owner = useNodeScope(
    () => props.projectId,
    () => {
      modules.value = [];
      artifacts.value = [];
      releases.value = [];
      placements.value = [];
      publication.value = null;
      details.value = null;
      busy.value = false;
      loading.value = false;
      live.invalidate();
    },
  );
  async function read() {
    const run = owner.capture();
    loading.value = true;
    try {
      const [result, current] = await Promise.all([
        gateway.catalog(props.projectId),
        gateway.placements(props.projectId),
      ]);
      if (owner.current(run)) {
        modules.value = result.modules;
        artifacts.value = result.artifacts;
        releases.value = result.releases;
        placements.value = current.items;
        error.value = "";
      }
    } catch {
      if (owner.current(run)) error.value = "Не удалось получить каталог образов MCP.";
    } finally {
      if (owner.current(run)) loading.value = false;
    }
  }
  const live = useLiveQuery(read, {
    enabled: () => !!props.projectId,
    topics: ["management.events"],
    accept: (event) => event.type === "node.modules" || event.type.startsWith("node.module."),
  });
  const rows = computed<LogicalModule[]>(() =>
    modules.value.map((module) => ({
      id: module.key,
      name: module.name,
      modules: module.components,
      components: artifacts.value.filter((item) => module.components.includes(item.key)),
    })),
  );
  function availability(row: LogicalModule) {
    const available = row.components.filter((item) => item.node_adapter).length;
    return row.modules.length === 1
      ? available
        ? "Доступен"
        : "Не готов"
      : `Доступен ${available} из ${row.modules.length}`;
  }
  function imageCount(row: LogicalModule) {
    return releases.value.filter((item) => row.modules.includes(item.module)).length;
  }
  const valid = computed(
    () =>
      /^[a-f0-9]{40}$/.test(commit.value) &&
      /^[a-f0-9]{64}$/.test(fingerprint.value) &&
      /^[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}$/.test(image.value),
  );
  function open(artifact: ModuleArtifact) {
    publication.value = artifact;
    commit.value = "";
    fingerprint.value = "";
    image.value = "";
    formError.value = "";
    operation = crypto.randomUUID();
    releaseId = crypto.randomUUID();
  }
  function openComponent(artifact: ModuleArtifact | undefined): void {
    if (artifact) open(artifact);
  }
  async function publish() {
    const run = owner.capture();
    if (!publication.value || busy.value || !valid.value) return;
    busy.value = true;
    formError.value = "";
    try {
      await gateway.command(props.projectId, {
        operation_uuid: operation,
        action: "modules",
        module: {
          action: "publish",
          publication: {
            id: releaseId,
            module: publication.value.key,
            source_commit: commit.value,
            input_fingerprint: fingerprint.value,
            image: image.value,
            platform: publication.value.inputs.platform,
          },
        },
      });
      if (!owner.current(run)) return;
      publication.value = null;
      live.invalidate();
    } catch {
      if (owner.current(run))
        formError.value =
          "Публикация не подтверждена. Проверьте registry, digest и неизменность сборки; повтор использует тот же идентификатор операции.";
    } finally {
      if (owner.current(run)) busy.value = false;
    }
  }

  return {
    artifacts,
    releases,
    loading,
    error,
    modules,
    placements,
    details,
    publication,
    busy,
    formError,
    commit,
    fingerprint,
    image,
    rows,
    availability,
    imageCount,
    valid,
    open,
    openComponent,
    publish,
  };
}
