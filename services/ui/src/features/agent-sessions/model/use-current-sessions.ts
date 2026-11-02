import { eventProjectId } from "@/shared/events";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import type { CurrentAgentSession } from "@/entities/agent-session";
import { useLiveQuery } from "@/shared/lib/use-live-query";
import { useProofLifetime } from "@/shared/lib/lifetime";
import { isUuid4 as isCurrentSessionId } from "@/shared/lib/uuid";
import type { SessionCommandPort, SessionInventory } from "./contracts";
import { pruneElapsedSessionRows } from "./prune-current-snapshot";
import {
  type ReconciledRevoke,
  revokeVerifiedSession,
  type SessionCommandContext,
} from "./revoke-current";
export type SessionLoadState =
  | "idle"
  | "loading"
  | "ready"
  | "unauthorized"
  | "denied"
  | "invalid"
  | "unavailable"
  | "stale";
type SessionNoticeKey =
  | "conflict"
  | "success"
  | "observed"
  | "uncertainty"
  | "unauthorized"
  | "denied"
  | "invalid"
  | "unavailable"
  | "proofExpired"
  | "stale";
type Fresh = "authorized" | "unauthorized" | "forbidden" | "unavailable";
export interface CurrentSessionsViewContext {
  renderless?: boolean;
  projectId?: string;
  actorNames?: Record<string, string>;
  actorId?: string;
  proofExpiresAt?: string;
  canList?: boolean;
  canApprove?: boolean;
  verifyApprover?: (signal: AbortSignal) => Promise<Fresh>;
  designPreview?: boolean;
  previewState?: "empty" | "loading" | "denied" | "unavailable";
}
function revocableInventorySelection(
  items: CurrentAgentSession[],
  item: CurrentAgentSession,
  project: string | undefined,
): boolean {
  const current = items.find((row) => row.session_uuid === item.session_uuid);
  return (
    !!current &&
    current.project_uuid === project &&
    current.revision === item.revision &&
    current.created_by_user_uuid === item.created_by_user_uuid &&
    current.status === "active" &&
    current.allowed_actions.includes("revoke") &&
    item.status === "active" &&
    Date.parse(item.hard_expires_at) > Date.now() &&
    item.allowed_actions.includes("revoke")
  );
}
function revokeFailure(kind: ReconciledRevoke["kind"]): SessionNoticeKey {
  const keys: Partial<Record<ReconciledRevoke["kind"], SessionNoticeKey>> = {
    uncertain: "uncertainty",
    unauthorized: "unauthorized",
    forbidden: "denied",
    invalid: "invalid",
  };
  return keys[kind] ?? "unavailable";
}
function inventoryFailure(kind: SessionInventory["kind"]): SessionLoadState {
  const status: Partial<Record<SessionInventory["kind"], SessionLoadState>> = {
    unauthorized: "unauthorized",
    forbidden: "denied",
    invalid: "invalid",
  };
  return status[kind] ?? "unavailable";
}
export function useCurrentSessions(props: CurrentSessionsViewContext, port: SessionCommandPort) {
  function acceptInventory(result: SessionInventory): void {
    if (result.kind === "ready") {
      items.value = result.items;
      status.value = "ready";
      const pending = confirmation.value;
      if (
        pending &&
        !result.items.some(
          (row) =>
            row.session_uuid === pending.session_uuid &&
            row.revision === pending.revision &&
            row.status === "active" &&
            row.allowed_actions.includes("revoke"),
        )
      ) {
        confirmation.value = null;
        errorKey.value = "conflict";
      }
    } else {
      confirmation.value = null;
      items.value = [];
      status.value = inventoryFailure(result.kind);
    }
  }
  function acceptRevoke(result: ReconciledRevoke): void {
    if (result.kind === "confirmed" || result.kind === "conflict" || result.kind === "observed") {
      items.value = items.value.map((row) =>
        row.session_uuid === result.item.session_uuid ? result.item : row,
      );
      status.value = "ready";
      if (result.kind === "confirmed") {
        infoKey.value = "success";
        lastTarget.value = null;
      } else if (result.kind === "observed") infoKey.value = "observed";
      else errorKey.value = "conflict";
    } else {
      // Do not leave actionable stale rows after an ambiguous or denied command.
      items.value = [];
      status.value = "unavailable";
      errorKey.value = revokeFailure(result.kind);
    }
  }
  function revokeContext(gen: number): SessionCommandContext | null {
    if (gen !== generation || !props.projectId || !props.actorId || props.canList !== true)
      return null;
    return {
      projectId: props.projectId,
      actorId: props.actorId,
      canApprove: props.canApprove === true,
      proofExpiresAt: props.proofExpiresAt ?? "",
    };
  }
  const status = ref<SessionLoadState>("idle");
  const items = ref<CurrentAgentSession[]>([]);
  const filtering = ref<"all" | "active" | "revoked" | "expired">("all");
  const search = ref("");
  const busy = ref(false);
  const refreshing = ref(false);
  const errorKey = ref<SessionNoticeKey | null>(null);
  const infoKey = ref<SessionNoticeKey | null>(null);
  const confirmation = ref<CurrentAgentSession | null>(null);
  const inspecting = ref<string | null>(null);
  const lookupId = ref("");
  const lookupOpen = ref(false);
  const lastTarget = ref<string | null>(null);
  const proofCurrent = useProofLifetime(() => props.proofExpiresAt);
  const snapshotExpiry = computed(() => {
    const active = items.value.filter((row) => row.status === "active");
    return active.length
      ? new Date(Math.min(...active.map((row) => Date.parse(row.hard_expires_at)))).toISOString()
      : null;
  });
  const snapshotCurrent = useProofLifetime(() => snapshotExpiry.value);
  let generation = 0;
  let controller: AbortController | null = null;
  let timeout: ReturnType<typeof setTimeout> | null = null;

  const canFetch = computed(
    () =>
      props.canList === true &&
      typeof props.projectId === "string" &&
      typeof props.actorId === "string" &&
      typeof props.proofExpiresAt === "string" &&
      proofCurrent.value &&
      Date.parse(props.proofExpiresAt) > Date.now(),
  );
  const shown = computed(() =>
    items.value.filter(
      (item) =>
        (filtering.value === "all" || item.status === filtering.value) &&
        (search.value.trim() === "" ||
          [item.session_uuid, item.created_by_user_uuid, ...item.operations].some((value) =>
            value.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase()),
          )),
    ),
  );
  const currentStatus = computed<SessionLoadState>(() =>
    props.designPreview
      ? props.previewState === "empty"
        ? "ready"
        : props.previewState === "loading"
          ? "loading"
          : props.previewState === "denied"
            ? "denied"
            : "unavailable"
      : status.value,
  );
  function cancel(): void {
    ++generation;
    controller?.abort();
    controller = null;
    if (timeout !== null) {
      clearTimeout(timeout);
      timeout = null;
    }
  }
  function reset(): void {
    cancel();
    items.value = [];
    status.value = "idle";
    errorKey.value = null;
    infoKey.value = null;
    busy.value = false;
    refreshing.value = false;
    confirmation.value = null;
    inspecting.value = null;
    lookupId.value = "";
    lastTarget.value = null;
  }
  function actionAllowed(item: CurrentAgentSession): boolean {
    if (
      props.designPreview ||
      status.value !== "ready" ||
      busy.value ||
      refreshing.value ||
      !canFetch.value ||
      props.canApprove !== true ||
      typeof props.verifyApprover !== "function"
    )
      return false;
    return revocableInventorySelection(items.value, item, props.projectId);
  }
  function finishRead(gen: number, request: AbortController): void {
    if (gen === generation) {
      if (request.signal.aborted) {
        confirmation.value = null;
        items.value = [];
        status.value = "unavailable";
      }
      timeout = null;
      controller = null;
      refreshing.value = false;
    }
  }
  async function refresh(): Promise<void> {
    if (busy.value) return;
    if (props.designPreview || !props.projectId || !props.actorId || !canFetch.value) {
      reset();
      return;
    }
    cancel();
    const request = new AbortController(),
      gen = ++generation;
    controller = request;
    refreshing.value = true;
    errorKey.value = null;
    infoKey.value = null;
    if (status.value !== "ready") status.value = "loading";
    const deadline = setTimeout(() => request.abort(), 8000);
    timeout = deadline;
    try {
      const result = await port.list(
        props.projectId,
        props.actorId,
        props.canApprove === true,
        request.signal,
      );
      if (gen !== generation || request.signal.aborted) return;
      acceptInventory(result);
    } finally {
      clearTimeout(deadline);
      finishRead(gen, request);
    }
  }
  function lookup(): void {
    const id = lookupId.value.trim();
    if (
      !props.designPreview &&
      canFetch.value &&
      !busy.value &&
      !refreshing.value &&
      isCurrentSessionId(id)
    ) {
      lookupOpen.value = false;
      inspecting.value = id;
    }
  }
  function requestRevoke(item: CurrentAgentSession): void {
    if (!actionAllowed(item)) return;
    confirmation.value = item;
  }
  async function confirmRevoke(): Promise<void> {
    const original = confirmation.value;
    if (
      !original ||
      !actionAllowed(original) ||
      !props.projectId ||
      !props.actorId ||
      !props.verifyApprover
    )
      return;
    cancel();
    const request = new AbortController(),
      gen = ++generation;
    controller = request;
    busy.value = true;
    errorKey.value = null;
    infoKey.value = null;
    lastTarget.value = original.session_uuid;
    const deadline = setTimeout(() => request.abort(), 9000);
    timeout = deadline;
    try {
      const result = await revokeVerifiedSession(original, {
        port,
        signal: request.signal,
        verify: props.verifyApprover,
        context: () => revokeContext(gen),
      });
      if (gen !== generation) return;
      confirmation.value = null;
      acceptRevoke(result);
    } finally {
      clearTimeout(deadline);
      if (gen === generation) {
        controller = null;
        timeout = null;
        busy.value = false;
      }
    }
  }
  watch(
    () => [props.projectId, props.actorId, props.canList, props.canApprove, props.designPreview],
    () => {
      reset();
      void refresh();
    },
    { flush: "sync" },
  );
  watch(
    () => props.proofExpiresAt,
    (value) => {
      if (!value || !(Date.parse(value) > Date.now())) {
        reset();
        return;
      }
    },
  );
  watch(
    proofCurrent,
    (current) => {
      if (!current) {
        reset();
        status.value = "denied";
        errorKey.value = "proofExpired";
      }
    },
    { flush: "sync" },
  );
  watch(
    [snapshotCurrent, busy, status],
    () => {
      if (
        !busy.value &&
        status.value === "ready" &&
        snapshotExpiry.value &&
        !snapshotCurrent.value
      ) {
        // useProofLifetime is monotonic: the clock can move backwards after an
        // expiry. At least the fired earliest deadline must remain irreversible.
        const cutoff = Math.max(Date.now(), Date.parse(snapshotExpiry.value));
        const aged = pruneElapsedSessionRows(items.value, cutoff);
        cancel();
        items.value = aged.items;
        if (
          confirmation.value &&
          !aged.items.some(
            (row) =>
              row.session_uuid === confirmation.value?.session_uuid &&
              row.revision === confirmation.value?.revision &&
              row.status === "active",
          )
        ) {
          confirmation.value = null;
        }
        refreshing.value = false;
        errorKey.value = null;
        // Other sessions are still valid *snapshots*, not fresh Cedar permits.
        // Do not duplicate the stale banner when no rows remain.
        infoKey.value = aged.items.length ? "stale" : null;
        status.value = aged.items.length ? "ready" : "stale";
        queueMicrotask(() => live.invalidate());
      }
    },
    { flush: "sync" },
  );
  const live = useLiveQuery(refresh, {
    enabled: () => canFetch.value && !props.designPreview,
    paused: () => busy.value,
    topics: ["management.events", "access.sessions"],
    accept: (event) =>
      event.type.startsWith("session.") && eventProjectId(event) === props.projectId,
  });

  onBeforeUnmount(reset);
  return {
    items,
    filtering,
    search,
    busy,
    refreshing,
    errorKey,
    infoKey,
    confirmation,
    inspecting,
    lookupId,
    lookupOpen,
    lastTarget,
    proofCurrent,
    canFetch,
    shown,
    currentStatus,
    actionAllowed,
    refresh,
    lookup,
    requestRevoke,
    confirmRevoke,
  };
}
