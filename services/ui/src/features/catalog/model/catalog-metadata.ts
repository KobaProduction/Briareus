import type { VerifiedPlatformContext } from "@/entities/workspace"

export type CatalogKind = "integration" | "variable"
export interface CatalogSummary {
  resource_uuid: string
  kind: CatalogKind
  owner: { kind: "project" | "team"; id: string }
  key: string
  version: number
}
export type CatalogMetadataResult =
  | { kind: "ready"; items: CatalogSummary[] }
  | { kind: "unauthorized" | "forbidden" | "invalid" | "unavailable"; code: string }
export const CATALOG_PAGE_LIMIT = 50
const UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const KEY = /^[A-Za-z0-9_.-]{1,128}$/
export function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}
export function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key))
}
export function validUuid(value: unknown): value is string {
  return typeof value === "string" && UUID4.test(value)
}
export function hasCurrentProject(context: VerifiedPlatformContext, project: string): boolean {
  return context.user.enabled === true && Date.parse(context.expires_at) > Date.now() &&
    context.projects.some(item => item.id === project && item.permissions.includes("use_resources"))
}
/** Nonsecret authority identity; renewal alone does not close an editor/dialog. */
export function catalogScopeFingerprint(context: VerifiedPlatformContext | null | undefined, project: string | null | undefined): string {
  const proof = context?.projects.find(item => item.id === project)
  return JSON.stringify([context?.user.id, context?.user.enabled, context?.user.role,
    context?.rauthy.issuer, context?.rauthy.subject, project, proof?.owner,
    [...(proof?.permissions ?? [])].sort(), context?.teams.map(team => team.id).sort()])
}
function currentOwner(value: unknown, project: string, context: VerifiedPlatformContext): CatalogSummary["owner"] | null {
  if (!isObject(value) || !exactKeys(value, ["kind", "id"]) || !validUuid(value.id)) return null
  if (value.kind === "project") return value.id === project ? { kind: "project", id: value.id } : null
  if (value.kind !== "team") return null
  const proof = context.projects.find(item => item.id === project)
  if (proof?.owner.kind !== "team" || proof.owner.id !== value.id || !context.teams.some(team => team.id === value.id)) return null
  return { kind: "team", id: value.id }
}
function catalogRow(value: unknown, project: string, kind: CatalogKind, context: VerifiedPlatformContext): CatalogSummary | null {
  if (!isObject(value) || !exactKeys(value, ["resource_uuid", "kind", "owner", "key", "version"])) return null
  if (!validUuid(value.resource_uuid) || value.kind !== kind || typeof value.key !== "string" || !KEY.test(value.key)) return null
  if (typeof value.version !== "number" || !Number.isSafeInteger(value.version) || value.version < 1) return null
  const owner = currentOwner(value.owner, project, context)
  return owner ? { resource_uuid: value.resource_uuid, kind, owner, key: value.key, version: value.version } : null
}
/** The whole page is rejected on foreign ownership, duplicates or secret fields. */
export function parseCatalogMetadata(data: unknown, project: string, kind: CatalogKind,
  context: VerifiedPlatformContext): CatalogSummary[] | null {
  if (!hasCurrentProject(context, project) || !isObject(data) || !exactKeys(data, ["items"])) return null
  if (!Array.isArray(data.items) || data.items.length > CATALOG_PAGE_LIMIT) return null
  const seen = new Set<string>(), result: CatalogSummary[] = []
  for (const value of data.items) {
    const row = catalogRow(value, project, kind, context)
    if (!row || seen.has(row.resource_uuid)) return null
    seen.add(row.resource_uuid)
    result.push(row)
  }
  return result
}
