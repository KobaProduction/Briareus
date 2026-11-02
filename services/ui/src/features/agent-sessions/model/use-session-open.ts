import { computed, onBeforeUnmount, ref, shallowRef, watch } from "vue";
import type { ElevationPolicy, NormalSession } from "@/entities/agent-session";
import { useProofLifetime } from "@/shared/lib/lifetime";
import type { SessionCommandPort } from "./contracts";
import {
  createSessionOpenRecovery,
  type PendingSessionOpen,
  type SessionOpenRecovery,
} from "./open-recovery";
import {
  type NormalOpenContext,
  openVerifiedNormalSession,
  type VerifiedNormalOpen,
} from "./open-verified";

type Fresh = "authorized" | "unauthorized" | "forbidden" | "unavailable";
export interface SessionOpenViewContext {
  projectId?: string;
  actorId?: string;
  ownerKey?: string;
  recovery?: SessionOpenRecovery;
  proofExpiresAt?: string;
  canOpen?: boolean;
  canApprove?: boolean;
  verifyUser?: (signal: AbortSignal) => Promise<Fresh>;
  designPreview?: boolean;
}
type OpenSessionOutcome =
  | "recoveryExpired"
  | "signedOut"
  | "denied"
  | "conflict"
  | "invalid"
  | "uncertain"
  | "unavailable";
function failureOutcome(
  next: Exclude<VerifiedNormalOpen, { kind: "created" }>,
): OpenSessionOutcome {
  if (next.code === "SESSION_RECOVERY_WINDOW_ELAPSED") return "recoveryExpired";
  const outcomes: Partial<Record<typeof next.kind, OpenSessionOutcome>> = {
    unauthorized: "signedOut",
    forbidden: "denied",
    conflict: "conflict",
    invalid: "invalid",
    uncertain: "uncertain",
  };
  return outcomes[next.kind] ?? "unavailable";
}
export function useSessionOpen(props: SessionOpenViewContext, port: SessionCommandPort) {
  const policy = ref<ElevationPolicy>("requestable");
  const label = ref("");
  const busy = ref(false);
  const result = ref<NormalSession | null>(null);
  const resultCurrent = useProofLifetime(() => result.value?.hard_expires_at);
  const expired = computed(() => result.value !== null && !resultCurrent.value);
  const recovered = ref(false);
  const inspectCurrent = ref(false);
  const outcomeKey = ref<OpenSessionOutcome | null>(null);
  const pending = shallowRef<PendingSessionOpen | null>(null);
  const localRecovery = createSessionOpenRecovery();
  const recovery = computed(() => props.recovery ?? localRecovery);
  let current: AbortController | null = null;
  let generation = 0;
  const proofCurrent = useProofLifetime(() => props.proofExpiresAt);
  const eligible = computed(
    () =>
      !props.designPreview &&
      props.canOpen === true &&
      typeof props.verifyUser === "function" &&
      typeof props.projectId === "string" &&
      typeof props.actorId === "string" &&
      typeof props.ownerKey === "string" &&
      typeof props.proofExpiresAt === "string" &&
      proofCurrent.value &&
      Date.parse(props.proofExpiresAt) > Date.now() &&
      !busy.value,
  );
  function stop(): void {
    ++generation;
    current?.abort();
    current = null;
  }
  function reset(): void {
    stop();
    result.value = null;
    inspectCurrent.value = false;
    recovered.value = false;
    outcomeKey.value = null;
    busy.value = false;
    pending.value =
      props.ownerKey && props.projectId
        ? recovery.value.get(props.ownerKey, props.projectId)
        : null;
    policy.value = pending.value?.command.policy ?? "requestable";
    label.value = pending.value?.command.label ?? "";
  }
  watch(
    () => [
      props.projectId,
      props.actorId,
      props.ownerKey,
      props.recovery,
      props.canOpen,
      props.designPreview,
    ],
    reset,
    { flush: "sync", immediate: true },
  );
  watch(
    () => props.proofExpiresAt,
    (value) => {
      if (!value || !(Date.parse(value) > Date.now())) reset();
    },
    { flush: "sync" },
  );
  watch(
    proofCurrent,
    (current) => {
      if (!current) reset();
    },
    { flush: "sync" },
  );
  onBeforeUnmount(() => {
    stop();
    localRecovery.clear();
    pending.value = null;
    result.value = null;
  });
  function commandContext(
    run: number,
    project: string,
    actor: string | undefined,
    owner: string,
  ): NormalOpenContext | null {
    if (
      run !== generation ||
      props.projectId !== project ||
      props.actorId !== actor ||
      props.ownerKey !== owner
    )
      return null;
    return {
      ownerKey: owner,
      projectId: project,
      actorId: actor ?? "",
      canOpen: props.canOpen === true && proofCurrent.value,
      proofExpiresAt: props.proofExpiresAt ?? "",
    };
  }
  async function create(retry = false): Promise<void> {
    if (!eligible.value || !props.verifyUser || !props.projectId || !props.ownerKey) return;
    const saved = pending.value;
    if ((retry && !saved) || (!retry && saved)) return;
    current?.abort();
    const request = new AbortController(),
      run = ++generation;
    const project = props.projectId,
      actor = props.actorId,
      owner = props.ownerKey,
      journal = recovery.value;
    current = request;
    busy.value = true;
    outcomeKey.value = null;
    const timeout = setTimeout(() => request.abort(), 9000);
    try {
      result.value = null;
      inspectCurrent.value = false;
      const next = await openVerifiedNormalSession({
        port,
        policy: policy.value,
        label: label.value,
        saved,
        journal,
        signal: request.signal,
        verify: props.verifyUser,
        context: () => commandContext(run, project, actor, owner),
      });
      if (run !== generation) return;
      pending.value = journal.get(owner, project);
      if (next.kind !== "created") {
        outcomeKey.value = failureOutcome(next);
        return;
      }
      result.value = next.session;
      recovered.value = retry;
    } finally {
      clearTimeout(timeout);
      if (current === request) {
        current = null;
        busy.value = false;
      }
    }
  }

  return {
    policy,
    label,
    busy,
    result,
    expired,
    recovered,
    inspectCurrent,
    outcomeKey,
    pending,
    eligible,
    create,
  };
}
