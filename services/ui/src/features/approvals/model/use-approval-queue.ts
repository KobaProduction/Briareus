import { eventProjectId } from "@/shared/events";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import {
  type ApprovalAction,
  type ApprovalRecord,
  approvalStillCurrentForActor,
} from "@/entities/approval";
import { useLiveQuery } from "@/shared/lib/use-live-query";
import { useProofLifetime } from "@/shared/lib/lifetime";
import type {
  ApprovalCommandContext,
  ApprovalCommandPort,
  ApprovalResult,
  CurrentApprovalResult,
} from "./contracts";
import { pruneElapsedApprovalRows } from "./prune-current-snapshot";
import { resolveCurrentApproval } from "./resolve-current";
export type ApprovalLoadState =
  | "idle"
  | "loading"
  | "ready"
  | "denied"
  | "expired"
  | "unavailable"
  | "invalid"
  | "stale";
type ApprovalNoticeKey =
  | "stale"
  | "observed"
  | "expired"
  | "denied"
  | "invalid"
  | "uncertain"
  | "unavailable"
  | "snapshotStale";
export interface ApprovalQueueContext {
  renderless?: boolean;
  projectId?: string;
  actorNames?: Record<string, string>;
  actorId?: string;
  proofExpiresAt?: string;
  canRead?: boolean;
  canApprove?: boolean;
  verifyApprover?: (
    signal: AbortSignal,
  ) => Promise<"authorized" | "unauthorized" | "forbidden" | "unavailable">;
  designPreview?: boolean;
  previewState?: "empty" | "loading" | "denied" | "unavailable";
}
function inventoryFailure(kind: ApprovalResult["kind"]): ApprovalLoadState {
  const states: Partial<Record<ApprovalResult["kind"], ApprovalLoadState>> = {
    unauthorized: "expired",
    forbidden: "denied",
    invalid: "invalid",
  };
  return states[kind] ?? "unavailable";
}
function decisionFailure(kind: CurrentApprovalResult["kind"]): ApprovalNoticeKey {
  const keys: Partial<Record<CurrentApprovalResult["kind"], ApprovalNoticeKey>> = {
    unauthorized: "expired",
    forbidden: "denied",
    invalid: "invalid",
    uncertain: "uncertain",
  };
  return keys[kind] ?? "unavailable";
}
export function useApprovalQueue(props: ApprovalQueueContext, port: ApprovalCommandPort) {
  function retainReadSelections(items: readonly ApprovalRecord[]): void {
    if (reviewedId.value && !items.some((row) => row.id === reviewedId.value))
      reviewedId.value = null;
    if (
      issued.value &&
      !items.some((row) => row.status === "approved" && row.issued_session_uuid === issued.value)
    )
      issued.value = null;
  }
  function clearEvidence(): void {
    confirmation.value = null;
    issued.value = null;
    reviewedId.value = null;
    records.value = [];
  }
  function acceptInventory(result: ApprovalResult): void {
    if (result.kind !== "ready") {
      clearEvidence();
      state.value = inventoryFailure(result.kind);
      return;
    }
    if (
      props.canApprove !== true &&
      result.items.some(
        (row) => row.requested_by_user_uuid !== props.actorId || row.allowed_actions.length !== 0,
      )
    ) {
      clearEvidence();
      state.value = "invalid";
      return;
    }
    records.value = result.items;
    state.value = "ready";
    retainReadSelections(result.items);
    const pending = confirmation.value;
    if (pending && !stillCurrentAction(pending.item, pending.action)) {
      confirmation.value = null;
      errorKey.value = "stale";
    }
  }
  function acceptDecision(result: CurrentApprovalResult): void {
    if (result.kind === "confirmed" || result.kind === "conflict" || result.kind === "observed") {
      records.value = result.items;
      state.value = "ready";
      if (result.kind === "conflict") errorKey.value = "stale";
      if (result.kind === "observed") observationKey.value = "observed";
    } else {
      // A failed/ambiguous POST must not leave stale actionable rows behind.
      records.value = [];
      state.value = "unavailable";
      errorKey.value = decisionFailure(result.kind);
    }
  }
  function decisionContext(gen: number): ApprovalCommandContext | null {
    if (gen !== generation || !props.projectId || !props.actorId || props.canRead !== true)
      return null;
    return {
      projectId: props.projectId,
      actorId: props.actorId,
      proofExpiresAt: props.proofExpiresAt ?? "",
      canApprove: props.canApprove === true,
      rows: records.value,
    };
  }
  const issued = ref<string | null>(null);
  const filter = ref<"all" | "pending" | "approved" | "rejected">("all");
  const query = ref("");
  const records = ref<ApprovalRecord[]>([]);
  const reviewedId = ref<string | null>(null);
  const reviewed = computed(() =>
    state.value === "ready"
      ? (records.value.find((row) => row.id === reviewedId.value) ?? null)
      : null,
  );
  const state = ref<ApprovalLoadState>("idle");
  const refreshing = ref(false);
  const mutating = ref(false);
  const errorKey = ref<ApprovalNoticeKey | null>(null);
  const observationKey = ref<ApprovalNoticeKey | null>(null);
  const confirmation = ref<{ item: ApprovalRecord; action: ApprovalAction } | null>(null);
  let controller: AbortController | null = null;
  let generation = 0;
  const proofCurrent = useProofLifetime(() => props.proofExpiresAt);
  const snapshotExpiry = computed(() => {
    const pending = records.value.filter(
      (row) => row.status === "pending" && row.allowed_actions.length > 0,
    );
    return pending.length
      ? new Date(
          Math.min(...pending.map((row) => Date.parse(row.requested_expires_at))),
        ).toISOString()
      : null;
  });
  const snapshotCurrent = useProofLifetime(() => snapshotExpiry.value);
  const canRead = computed(
    () =>
      props.canRead === true &&
      typeof props.actorId === "string" &&
      typeof props.projectId === "string" &&
      typeof props.proofExpiresAt === "string" &&
      proofCurrent.value &&
      Date.parse(props.proofExpiresAt) > Date.now(),
  );
  const approver = computed(
    () => props.canApprove === true && typeof props.verifyApprover === "function",
  );
  const shown = computed(() =>
    records.value.filter(
      (row) =>
        (filter.value === "all" || row.status === filter.value) &&
        (query.value.trim() === "" ||
          [
            row.id,
            row.agent_session_uuid,
            row.requested_by_user_uuid,
            ...row.requested_operations,
          ].some((x) => x.toLowerCase().includes(query.value.toLowerCase().trim()))),
    ),
  );
  const displayState = computed<ApprovalLoadState>(() =>
    props.designPreview
      ? props.previewState === "empty"
        ? "ready"
        : props.previewState === "loading"
          ? "loading"
          : props.previewState === "denied"
            ? "denied"
            : "unavailable"
      : state.value,
  );
  function reset(): void {
    ++generation;
    controller?.abort();
    controller = null;
    records.value = [];
    state.value = "idle";
    confirmation.value = null;
    issued.value = null;
    reviewedId.value = null;
    errorKey.value = null;
    observationKey.value = null;
    refreshing.value = false;
    mutating.value = false;
  }
  function finishRead(gen: number, current: AbortController): void {
    if (gen === generation) {
      if (current.signal.aborted) {
        confirmation.value = null;
        issued.value = null;
        reviewedId.value = null;
        records.value = [];
        state.value = "unavailable";
      }
      refreshing.value = false;
      controller = null;
    }
  }
  async function refresh(): Promise<void> {
    if (mutating.value) return;
    if (props.designPreview || !props.projectId || !canRead.value) {
      reset();
      return;
    }
    controller?.abort();
    const current = new AbortController(),
      gen = ++generation;
    controller = current;
    refreshing.value = true;
    errorKey.value = null;
    observationKey.value = null;
    if (state.value !== "ready") state.value = "loading";
    const timer = setTimeout(() => current.abort(), 8000);
    try {
      const result = await port.read(props.projectId, current.signal);
      if (gen !== generation || current.signal.aborted) return;
      acceptInventory(result);
    } finally {
      clearTimeout(timer);
      finishRead(gen, current);
    }
  }
  const canChoose = computed(
    () =>
      !props.designPreview &&
      state.value === "ready" &&
      !refreshing.value &&
      !mutating.value &&
      canRead.value &&
      approver.value,
  );
  function stillCurrentAction(row: ApprovalRecord, action: ApprovalAction): boolean {
    return (
      !!props.projectId &&
      !!props.actorId &&
      approvalStillCurrentForActor(row, records.value, action, props.projectId, props.actorId)
    );
  }
  function allowAction(row: ApprovalRecord, action: ApprovalAction): boolean {
    return canChoose.value && stillCurrentAction(row, action);
  }
  function requestAction(row: ApprovalRecord, action: ApprovalAction): void {
    if (!allowAction(row, action)) return;
    confirmation.value = { item: row, action };
  }
  async function confirmAction(): Promise<void> {
    const pending = confirmation.value;
    if (
      !pending ||
      mutating.value ||
      !props.verifyApprover ||
      !props.projectId ||
      !props.actorId ||
      !allowAction(pending.item, pending.action)
    )
      return;
    mutating.value = true;
    errorKey.value = null;
    observationKey.value = null;
    const current = new AbortController(),
      gen = ++generation;
    controller?.abort();
    controller = current;
    const timer = setTimeout(() => current.abort(), 9000);
    try {
      const result = await resolveCurrentApproval(pending.item, pending.action, {
        port,
        signal: current.signal,
        verify: props.verifyApprover,
        context: () => decisionContext(gen),
      });
      if (gen !== generation) return;
      confirmation.value = null;
      acceptDecision(result);
    } finally {
      clearTimeout(timer);
      if (gen === generation) {
        controller = null;
        mutating.value = false;
      }
    }
  }
  watch(
    () => [props.projectId, props.actorId, props.canRead, props.canApprove, props.designPreview],
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
        state.value = "expired";
        return;
      }
    },
  );
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
  watch(
    [snapshotCurrent, mutating, state],
    () => {
      if (
        !mutating.value &&
        state.value === "ready" &&
        snapshotExpiry.value &&
        !snapshotCurrent.value
      ) {
        // Age only the fired pending decision(s). A retired request MUST NOT
        // clear other unexpired approvals or historical owner records.
        // The monotonic snapshot deadline remains irrevocable on clock rollback.
        const cutoff = Math.max(Date.now(), Date.parse(snapshotExpiry.value));
        const aged = pruneElapsedApprovalRows(records.value, cutoff);
        records.value = aged.items;
        if (
          confirmation.value &&
          !aged.items.some(
            (row) =>
              row.id === confirmation.value?.item.id &&
              row.version === confirmation.value?.item.version,
          )
        ) {
          confirmation.value = null;
        }
        retainReadSelections(aged.items);
        errorKey.value = null;
        observationKey.value = aged.items.length ? "snapshotStale" : null;
        state.value = aged.items.length ? "ready" : "stale";
      }
    },
    { flush: "sync" },
  );
  useLiveQuery(refresh, {
    enabled: () => canRead.value && !props.designPreview,
    paused: () => mutating.value,
    topics: ["management.events", "access.sessions"],
    accept: (event) =>
      event.type.startsWith("session.") && eventProjectId(event) === props.projectId,
  });

  onBeforeUnmount(reset);
  return {
    issued,
    filter,
    query,
    records,
    reviewedId,
    reviewed,
    refreshing,
    mutating,
    errorKey,
    observationKey,
    confirmation,
    canRead,
    shown,
    displayState,
    allowAction,
    requestAction,
    confirmAction,
  };
}
