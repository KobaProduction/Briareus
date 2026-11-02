import { decodeBffOwnerEvidence, decodeBffEffectEvidence } from "./bff-evidence-decoder";
import {
  canonicalUuid4,
  type PlatformPort,
  type QueryContext,
  type ScopeSelection,
  type SourceCommandBinding,
  type UiCapability,
} from "./contracts";

/** Selected B15 ownership model. These are DOMAIN OWNERS behind one BFF,
 * not browser-addressable database/service origins or HTTP wire DTOs. */
export type BffOwner = "identity" | "access" | "control" | "catalog";
export type OwnerAvailability = "ready" | "upgrading" | "unavailable" | "unknown";
export type OwnerEffectPhase = "pending" | "unknown" | "reconciling" | "confirmed" | "denied";
export const BFF_OWNERS = ["identity", "access", "control", "catalog"] as const;
export const OWNER_PROOF_MAX_AGE_MS = 60_000;
const UTC_AWARE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})$/i;

export interface BffOwnerState {
  readonly availability: OwnerAvailability;
  /** Opaque authoritative per-owner revision, never a SQL migration head. */
  readonly revision: string | null;
}
/** This may ONLY be produced by a source-reviewed authenticated BFF port.
 * Constructing this shape in the browser is NOT a trust grant. */
export interface BffOwnerEvidence {
  readonly actorUserId: string;
  readonly scope: ScopeSelection;
  readonly observedAtUtc: string;
  readonly expiresAtUtc: string;
  readonly owners: Readonly<Record<BffOwner, BffOwnerState>>;
}
export interface BffOwnerEffect {
  readonly phase: OwnerEffectPhase;
  /** Signed source owner revision from the SAME authenticated BFF view. */
  readonly revision: string;
}
export interface BffEffectEvidence {
  readonly actorUserId: string;
  readonly scope: ScopeSelection;
  readonly binding: SourceCommandBinding;
  readonly idempotencyKey: string;
  /** A11 Operation-UUID, independently bound to signed owner-local effect. */
  readonly operationUuid: string;
  readonly phase: OwnerEffectPhase;
  readonly owners: Readonly<Partial<Record<BffOwner, BffOwnerEffect>>>;
  readonly observedAtUtc: string;
}
/** Independently SOURCE-accepted Backend A13 returns original operationUuid
 * bound by owner-signed statuses and requires an identical canonical UUIDv4
 * Idempotency-Key. This interface is NOT a browser-side signature verifier.
 * Never synthesize or echo the request UUID as result evidence; a physically
 * authenticated BFF/owner transport is still gated by D4 and C1-B2/C2. */
export interface AuthenticatedBffBoundary {
  current(context: QueryContext): Promise<BffOwnerEvidence>;
  inspectOriginalCommand?(
    context: QueryContext,
    input: {
      binding: SourceCommandBinding;
      idempotencyKey: string;
      operationUuid: string;
    },
  ): Promise<BffEffectEvidence>;
}
/** Composition boundary, no direct browser access to owner DBs or services. */
export interface BffDomainCapabilities {
  readonly identity: Pick<PlatformPort, "auth" | "users">;
  readonly access: Pick<PlatformPort, "sessions" | "realtime">;
  readonly control: Pick<PlatformPort, "teams" | "projects" | "agents" | "operator">;
  readonly catalog: Pick<PlatformPort, "accounts" | "variables" | "providers">;
  readonly boundary: AuthenticatedBffBoundary;
}
export function groupVerifiedBffCapabilities(port: PlatformPort): BffDomainCapabilities | null {
  if (!port.bff) return null;
  return {
    identity: { auth: port.auth, users: port.users },
    access: { sessions: port.sessions, realtime: port.realtime },
    control: {
      teams: port.teams,
      projects: port.projects,
      agents: port.agents,
      operator: port.operator,
    },
    catalog: { accounts: port.accounts, variables: port.variables, providers: port.providers },
    boundary: port.bff,
  };
}
export function sameBffScope(a: ScopeSelection, b: ScopeSelection): boolean {
  if (a.kind !== b.kind) return false;
  if (a.kind === "project") return b.kind === "project" && a.projectId === b.projectId;
  if (a.kind === "team") return b.kind === "team" && a.teamId === b.teamId;
  return true;
}
const validRevision = (value: unknown): value is string =>
  typeof value === "string" &&
  value.length > 0 &&
  value.length <= 160 &&
  /^[A-Za-z0-9_.:-]+$/.test(value);
const validUtc = (value: unknown): value is string =>
  typeof value === "string" &&
  value.length <= 64 &&
  UTC_AWARE.test(value) &&
  Number.isFinite(Date.parse(value));
/** Pure format/date/scope defense in depth; ONLY an approved BFF installer
 * can supply the authoritative source. No local proof minting or bypass. */
function currentOwnerTimeline(value: BffOwnerEvidence, now: number): boolean {
  if (!Number.isFinite(now) || !validUtc(value.observedAtUtc) || !validUtc(value.expiresAtUtc))
    return false;
  const observed = Date.parse(value.observedAtUtc),
    expires = Date.parse(value.expiresAtUtc);
  return (
    observed <= now + 5_000 &&
    expires > now &&
    expires > observed &&
    expires - observed <= OWNER_PROOF_MAX_AGE_MS
  );
}
function validOwnerState(value: BffOwnerState): boolean {
  return value.availability === "ready" ? validRevision(value.revision) : value.revision === null;
}
export function verifiedBffEvidence(
  value: unknown,
  actor: string,
  scope: ScopeSelection,
  now = Date.now(),
): value is BffOwnerEvidence {
  const evidence = decodeBffOwnerEvidence(value);
  if (!evidence || !actor || evidence.actorUserId !== actor || !sameBffScope(evidence.scope, scope))
    return false;
  return (
    currentOwnerTimeline(evidence, now) &&
    BFF_OWNERS.every((owner) => validOwnerState(evidence.owners[owner]))
  );
}
/** Identity + Access + Control are ALWAYS current for a privileged effect.
 * Catalog adds its own owner proof for credentials/variables and providers. */
export function requiredOwners(action: UiCapability): readonly BffOwner[] {
  const common: readonly BffOwner[] = ["identity", "access", "control"];
  return action.startsWith("accounts.") || action.startsWith("variables.")
    ? [...common, "catalog"]
    : common;
}
export function isPrivilegedAction(action: UiCapability): boolean {
  return ![
    "profile.read",
    "users.read",
    "teams.read",
    "projects.read",
    "agents.read",
    "sessions.read",
    "accounts.read",
    "variables.read",
    "operations.metadata.read",
    "dashboard.read",
    "calls.read",
    "oauth.read",
    "files.read",
    "terminal.read",
    "browser.managed.read",
    "browser.external.read",
    "analysis.read",
    "settings.read",
  ].includes(action);
}
/** Local owner-local ACK is NOT a distributed commit. A multi-owner effect is
 * confirmed only after BFF source reports every required owner confirmed. */
export interface BffEffectExpectation {
  actor: string;
  scope: ScopeSelection;
  binding: SourceCommandBinding;
  idempotencyKey: string;
  operationUuid: string;
  action: UiCapability;
  ownerEvidence: BffOwnerEvidence;
}
function matchingEffectBinding(
  actual: SourceCommandBinding,
  expected: SourceCommandBinding,
): boolean {
  if (
    actual.operation !== expected.operation ||
    actual.target.kind !== expected.target.kind ||
    actual.target.id !== expected.target.id
  )
    return false;
  if (actual.target.kind !== "resource") return true;
  return (
    expected.target.kind === "resource" && sameBffScope(actual.target.owner, expected.target.owner)
  );
}
function originalEffectIdentity(value: BffEffectEvidence, input: BffEffectExpectation): boolean {
  return (
    canonicalUuid4(input.operationUuid) &&
    input.idempotencyKey === input.operationUuid &&
    value.phase === "confirmed" &&
    value.actorUserId === input.actor &&
    sameBffScope(value.scope, input.scope) &&
    value.idempotencyKey === input.idempotencyKey &&
    value.operationUuid === input.operationUuid &&
    matchingEffectBinding(value.binding, input.binding)
  );
}
function confirmedOwnerRevision(
  actual: BffOwnerEffect | undefined,
  expected: BffOwnerState,
): boolean {
  return (
    actual?.phase === "confirmed" &&
    validRevision(actual.revision) &&
    expected.availability === "ready" &&
    actual.revision === expected.revision
  );
}
export function confirmedBffEffect(
  value: unknown,
  input: BffEffectExpectation,
  now = Date.now(),
): boolean {
  const evidence = decodeBffEffectEvidence(value);
  // Source identity remains bound to BOTH original UUID headers. This local
  // policy validates the normalized source facts; it never verifies a signature.
  if (!evidence || !originalEffectIdentity(evidence, input) || !Number.isFinite(now)) return false;
  if (
    !validUtc(evidence.observedAtUtc) ||
    Math.abs(now - Date.parse(evidence.observedAtUtc)) > OWNER_PROOF_MAX_AGE_MS
  )
    return false;
  if (!verifiedBffEvidence(input.ownerEvidence, input.actor, input.scope, now)) return false;
  return requiredOwners(input.action).every((owner) =>
    confirmedOwnerRevision(evidence.owners[owner], input.ownerEvidence.owners[owner]),
  );
}
/** A source-owned saga may involve several databases; never infer completion
 * from one Project/Team mutation 2xx or an eventually delivered WS event. */
/** Every privileged action may span authoritative owner stores or revoke
 * downstream grants; never infer distributed success from local HTTP 2xx.
 * Only non-mutating read projections may be shown without owner effect ACK. */
export function crossOwnerMutation(action: UiCapability): boolean {
  return isPrivilegedAction(action);
}
