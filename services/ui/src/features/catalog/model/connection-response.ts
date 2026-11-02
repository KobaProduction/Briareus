import { isObject, validUuid } from "./catalog-metadata"
import { connectionProviders, validConnectionProvider, validConnectionAuth,
  type ConnectionConfiguration, type GitPolicy, type ConnectionProvider } from "./connection-draft"
import type { Connection, ConnectionForms, ConnectionPage, ConnectionProbe, ConnectionSubmission } from "./connection-contracts"

function stringList(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length > 64) return null
  const result: string[] = []
  for (const item of value) {
    if (typeof item !== "string" || !item.trim() || item.length > 128) return null
    if ([...item].some(character => character.charCodeAt(0) < 32)) return null
    result.push(item)
  }
  return result
}
function gitPolicy(value: unknown): GitPolicy | null {
  if (!isObject(value)) return null
  const branches = stringList(value.protected_branches)
  if (!branches || typeof value.local_first_guidance !== "boolean" || typeof value.local_git_transport_enabled !== "boolean" ||
    typeof value.remote_source_mutations_enabled !== "boolean") return null
  const checks = value.required_checks === undefined ? undefined : stringList(value.required_checks)
  const reviewers = value.required_reviewers === undefined ? undefined : stringList(value.required_reviewers)
  if (checks === null || reviewers === null) return null
  return { protected_branches: branches, local_first_guidance: value.local_first_guidance,
    local_git_transport_enabled: value.local_git_transport_enabled, remote_source_mutations_enabled: value.remote_source_mutations_enabled,
    ...(checks ? { required_checks: checks } : {}), ...(reviewers ? { required_reviewers: reviewers } : {}) }
}
function configuration(value: unknown, provider: ConnectionProvider, name: string,
  auth: string, baseUrl: string): ConnectionConfiguration | null {
  if (!isObject(value) || value.provider !== provider || value.name !== name || value.auth_type !== auth) return null
  const allowed = new Set(["name", "provider", "auth_type", "base_url", "ca_cert_pem", "external_id", "git_policy"])
  if (Object.keys(value).some(key => !allowed.has(key))) return null
  const base = value.base_url ?? baseUrl, certificate = value.ca_cert_pem ?? "", external = value.external_id ?? ""
  if (typeof base !== "string" || typeof certificate !== "string" || typeof external !== "string") return null
  const policy = value.git_policy === undefined ? undefined : gitPolicy(value.git_policy)
  if (policy === null) return null
  // Copy only reviewed metadata fields; credential-like extras never enter a draft.
  return { name, provider, auth_type: auth, base_url: base, ca_cert_pem: certificate,
    ...(provider === "github" ? { external_id: external } : {}), ...(policy ? { git_policy: policy } : {}) }
}
export function parseConnection(value: unknown): Connection | null {
  if (!isObject(value) || !validUuid(value.id) || !validConnectionProvider(value.provider)) return null
  if (typeof value.name !== "string" || typeof value.base_url !== "string" || !validConnectionAuth(value.provider, value.auth_type)) return null
  if (typeof value.revision !== "number" || !Number.isSafeInteger(value.revision) || value.revision < 1) return null
  const settings = configuration(value.configuration, value.provider, value.name, value.auth_type, value.base_url)
  return settings ? { id: value.id, name: value.name, provider: value.provider, base_url: value.base_url,
    auth_type: value.auth_type, revision: value.revision, configuration: settings } : null
}
export function parseConnectionPage(value: unknown): ConnectionPage | null {
  if (!isObject(value) || !Array.isArray(value.items) || value.items.length > 50 || typeof value.has_more !== "boolean") return null
  const items: Connection[] = [], seen = new Set<string>()
  for (const candidate of value.items) {
    const row = parseConnection(candidate)
    if (!row || seen.has(row.id)) return null
    seen.add(row.id)
    items.push(row)
  }
  if (value.has_more && (typeof value.next_cursor !== "string" || !value.next_cursor || value.next_cursor.length > 1024)) return null
  return { items, hasMore: value.has_more, nextCursor: value.has_more ? String(value.next_cursor) : null }
}
export function parseConnectionProbe(value: unknown): ConnectionProbe | null {
  if (!isObject(value) || !(value.status === "connected" || value.status === "denied" || value.status === "unavailable")) return null
  if (value.identity !== undefined && value.identity !== null && typeof value.identity !== "string") return null
  return { status: value.status, identity: typeof value.identity === "string" ? value.identity.slice(0, 128) : null }
}
export function parseConnectionSubmission(value: unknown): ConnectionSubmission | null {
  if (isObject(value) && value.item !== undefined) {
    const item = parseConnection(value.item)
    return item ? { item } : null
  }
  return parseConnectionProbe(value)
}
function sourceFormSupports(value: unknown, provider: ConnectionProvider): boolean {
  if (!isObject(value) || !isObject(value.properties)) return false
  const properties = value.properties
  if (!isObject(properties.provider) || properties.provider.const !== provider || !isObject(properties.credential)) return false
  if (properties.credential.writeOnly !== true || !isObject(properties.auth_type)) return false
  const options: unknown[] = Array.isArray(properties.auth_type.enum) ? properties.auth_type.enum : [properties.auth_type.const]
  return connectionProviders[provider].auth.every(auth => options.includes(auth))
}
/** Review the owner-provided discriminated schema, never assume forms from a 2xx. */
export function parseConnectionForms(value: unknown): ConnectionForms | null {
  if (!isObject(value) || !isObject(value.$defs) || !isObject(value.discriminator) || !isObject(value.discriminator.mapping)) return null
  if (value.discriminator.propertyName !== "provider") return null
  const providers: ConnectionProvider[] = []
  for (const provider of Object.keys(connectionProviders)) {
    if (!validConnectionProvider(provider)) continue
    const reference = value.discriminator.mapping[provider]
    if (typeof reference !== "string" || !reference.startsWith("#/$defs/")) continue
    if (sourceFormSupports(value.$defs[reference.slice(8)], provider)) providers.push(provider)
  }
  return providers.length ? { providers } : null
}
export function parseConnectionDeleted(value: unknown): { deleted: true } | null {
  return isObject(value) && value.deleted === true ? { deleted: true } : null
}
