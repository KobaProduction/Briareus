import { eventProjectId } from "@/shared/events";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import type { VerifiedPlatformContext } from "@/entities/workspace";
import { useProofLifetime } from "@/shared/lib/lifetime";
import { useLiveQuery } from "@/shared/lib/use-live-query";
import { readCurrentCatalog } from "../api/current-metadata";
import {
  catalogScopeFingerprint,
  hasCurrentProject,
  type CatalogKind,
  type CatalogMetadataResult,
  type CatalogSummary,
} from "./catalog-metadata";

export type CatalogReadStatus =
  | "idle"
  | "loading"
  | "ready"
  | "unauthorized"
  | "denied"
  | "invalid"
  | "unavailable"
  | "expired";
interface CatalogQuery {
  context: () => VerifiedPlatformContext | null | undefined;
  project: () => string | null | undefined;
  kind: () => CatalogKind;
  designPreview: () => boolean;
}
export function useCatalogMetadata(query: CatalogQuery) {
  const state = ref<CatalogReadStatus>("idle"),
    records = ref<CatalogSummary[]>([]),
    busy = ref(false);
  const detailId = ref<string | null>(null),
    selectionNotice = ref(false);
  const proofCurrent = useProofLifetime(() => query.context()?.expires_at);
  const eligible = computed(() =>
    proofCurrent.value
      ? (query.context()?.projects.filter((row) => row.permissions.includes("use_resources")) ?? [])
      : [],
  );
  const selectedProof = computed(() => eligible.value.find((row) => row.id === query.project()));
  const canFetch = computed(() => {
    const context = query.context(),
      project = query.project();
    return Boolean(context && project && proofCurrent.value && hasCurrentProject(context, project));
  });
  const fingerprint = computed(() => catalogScopeFingerprint(query.context(), query.project()));
  let controller: AbortController | null = null,
    generation = 0;
  let deadline: ReturnType<typeof setTimeout> | null = null;
  function cancel(): void {
    ++generation;
    controller?.abort();
    controller = null;
    if (deadline !== null) {
      clearTimeout(deadline);
      deadline = null;
    }
  }
  function reset(clearSelection = true): void {
    cancel();
    if (clearSelection) {
      detailId.value = null;
      selectionNotice.value = false;
    }
    records.value = [];
    state.value = "idle";
    busy.value = false;
  }
  function blockRead(): void {
    reset(false);
    detailId.value = null;
    if (query.context() && !proofCurrent.value) state.value = "expired";
    else if (query.context() && query.project() && !canFetch.value) state.value = "denied";
  }
  function apply(result: CatalogMetadataResult): void {
    if (result.kind !== "ready") {
      detailId.value = null;
      state.value = result.kind === "forbidden" ? "denied" : result.kind;
      return;
    }
    records.value = result.items;
    state.value = "ready";
    if (detailId.value && !result.items.some((row) => row.resource_uuid === detailId.value)) {
      detailId.value = null;
      selectionNotice.value = true;
    }
  }
  function release(
    request: AbortController,
    run: number,
    timer: ReturnType<typeof setTimeout>,
  ): void {
    clearTimeout(timer);
    if (run !== generation) return;
    if (request.signal.aborted) {
      detailId.value = null;
      records.value = [];
      state.value = "unavailable";
    }
    busy.value = false;
    controller = null;
    deadline = null;
  }
  async function reload(): Promise<void> {
    cancel();
    const context = query.context(),
      project = query.project();
    if (query.designPreview() || !context || !project || !canFetch.value) {
      blockRead();
      return;
    }
    const request = new AbortController(),
      run = ++generation,
      authority = fingerprint.value;
    controller = request;
    busy.value = true;
    if (state.value !== "ready") state.value = "loading";
    const timer = setTimeout(() => request.abort(), 8_000);
    deadline = timer;
    try {
      const result = await readCurrentCatalog(project, query.kind(), context, request.signal);
      if (run !== generation || request.signal.aborted || authority !== fingerprint.value) return;
      if (!canFetch.value) {
        blockRead();
        return;
      }
      apply(result);
    } finally {
      release(request, run, timer);
    }
  }
  watch([fingerprint, query.kind], () => reset(), { flush: "sync" });
  watch(
    proofCurrent,
    (current) => {
      if (!current) {
        reset();
        state.value = "expired";
      }
    },
    { flush: "sync" },
  );
  const liveQuery = useLiveQuery(reload, {
    enabled: () => canFetch.value && !query.designPreview(),
    topics: ["management.events"],
    accept: (event) => eventProjectId(event) === query.project(),
  });
  watch([fingerprint, canFetch, query.kind, query.designPreview], () => liveQuery.invalidate());
  onBeforeUnmount(() => reset());
  return {
    state,
    records,
    busy,
    detailId,
    selectionNotice,
    proofCurrent,
    eligible,
    selectedProof,
    canFetch,
    reload,
    reset,
  };
}
