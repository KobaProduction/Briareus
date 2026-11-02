import { eventProjectId } from "@/shared/events";
import { onBeforeUnmount, ref, watch } from "vue";
import type { CurrentAgentSession } from "@/entities/agent-session";
import { useLiveQuery } from "@/shared/lib/use-live-query";
import { useProofLifetime } from "@/shared/lib/lifetime";
import type { CurrentSessionRead, SessionCommandPort } from "./contracts";
export interface SessionInspectorContext {
  projectId: string;
  sessionId: string;
  actorId: string;
  proofExpiresAt: string;
  canList: boolean;
  canApprove: boolean;
}
export function useSessionInspector(
  props: SessionInspectorContext,
  readCurrentSession: SessionCommandPort["read"],
) {
  const state = ref<
    | "loading"
    | "ready"
    | "not_found"
    | "unauthorized"
    | "forbidden"
    | "invalid"
    | "unavailable"
    | "expired"
    | "stale"
  >("loading");
  const item = ref<CurrentAgentSession | null>(null);
  let generation = 0,
    request: AbortController | null = null;
  let deadline: ReturnType<typeof setTimeout> | null = null;
  const proofCurrent = useProofLifetime(() => props.proofExpiresAt);
  const activeSnapshotCurrent = useProofLifetime(() =>
    item.value?.status === "active" ? item.value.hard_expires_at : null,
  );
  function acceptResult(result: CurrentSessionRead): void {
    if (result.kind !== "ready") {
      state.value = result.kind === "conflict" ? "unavailable" : result.kind;
      return;
    }
    item.value = result.item;
    if (!proofCurrent.value) {
      invalidate();
      state.value = "expired";
    } else if (result.item.status === "active" && !activeSnapshotCurrent.value) {
      invalidate();
      state.value = "stale";
    } else state.value = "ready";
  }
  function invalidate(): void {
    ++generation;
    request?.abort();
    request = null;
    if (deadline !== null) {
      clearTimeout(deadline);
      deadline = null;
    }
    item.value = null;
  }
  async function refresh(): Promise<void> {
    invalidate();
    const remaining = Date.parse(props.proofExpiresAt) - Date.now();
    if (!props.canList) {
      state.value = "forbidden";
      return;
    }
    if (!proofCurrent.value || !(remaining > 0)) {
      state.value = "expired";
      return;
    }
    const controller = new AbortController(),
      run = ++generation;
    request = controller;
    state.value = "loading";
    deadline = setTimeout(() => controller.abort(), 8000);
    try {
      const result = await readCurrentSession(
        props.projectId,
        props.sessionId,
        props.actorId,
        props.canApprove,
        controller.signal,
      );
      if (run !== generation) return;
      if (controller.signal.aborted) {
        state.value = "unavailable";
        return;
      }
      acceptResult(result);
    } finally {
      if (run === generation) {
        if (deadline !== null) {
          clearTimeout(deadline);
          deadline = null;
        }
        request = null;
      }
    }
  }
  watch(
    proofCurrent,
    (current) => {
      if (!current) {
        invalidate();
        state.value = "expired";
      }
    },
    { flush: "sync" },
  );
  watch(
    activeSnapshotCurrent,
    (current) => {
      if (!current && item.value?.status === "active") {
        invalidate();
        state.value = "stale";
      }
    },
    { flush: "sync" },
  );
  watch(
    () => [props.projectId, props.sessionId, props.actorId, props.canList, props.canApprove],
    () => {
      void refresh();
    },
  );
  useLiveQuery(refresh, {
    enabled: () => proofCurrent.value && props.canList,
    topics: ["management.events", "access.sessions"],
    accept: (event) =>
      event.type.startsWith("session.") && eventProjectId(event) === props.projectId,
  });
  onBeforeUnmount(invalidate);
  return { state, item };
}
