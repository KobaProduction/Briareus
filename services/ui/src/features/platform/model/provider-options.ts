/** Mirrors current projects/_provider_registry.py, not legacy Admin AccountPayload. */
export const providerCatalog = {
  github: ["personal_token", "github_app"],
  gitlab: ["personal_token", "oauth"],
  coolify: ["api_token"],
  signoz: ["api_token"],
  grafana: ["api_token"],
  zoomies: ["api_token"],
} as const
export type SourceProviderName = keyof typeof providerCatalog
export interface SourceProviderDraft {
  provider: SourceProviderName
  authType: string
  baseUrl: string
  displayName: string
  installationId: string
  organization: string
  namespace: string
  tenant: string
}
// This mirrors accepted Backend A5 Pydantic string field constraints for
// presentation only. Backend DNS/SSRF/credential validation is authoritative.
const githubOrganization = /^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$/
const gitlabNamespace = /^[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+)*$/
const infrastructureTenant = /^[A-Za-z0-9][A-Za-z0-9_-]*$/
const aliasPattern = /^[A-Za-z][A-Za-z0-9_.-]{0,127}$/
const variableNamePattern = /^[A-Z_][A-Z0-9_]{0,127}$/
export const validResourceAlias = (value: string) => aliasPattern.test(value.trim())
export const validVariableName = (value: string) => variableNamePattern.test(value.trim().toUpperCase())
/** Accepted A11 Catalog owner `_secret_digest` accepts 1..131072 UTF-8
 * bytes. This is validation only; a signed current Catalog BFF grant and
 * owner-local encryption/SSRF controls remain server responsibilities. */
export function validCatalogValue(value:string):boolean {
  if(!value)return false
  const length=new TextEncoder().encode(value).byteLength
  return length>=1&&length<=131_072
}
export function providerAuthTypes(provider: SourceProviderName): readonly string[] { return providerCatalog[provider] }
export type SourceProviderOptions = {
  base_url: string
  display_name: string
  installation_id?: number
  organization?: string
  namespace?: string
  tenant?: string
}
function containsControl(value: string): boolean {
  return [...value].some(character => {
    const code = character.charCodeAt(0)
    return code < 32 || code === 127
  })
}
function validProviderFields(value: SourceProviderDraft): boolean {
  const labels = [value.displayName, value.organization, value.namespace, value.tenant]
  return labels.every(item => item.length <= 128) &&
    ![value.baseUrl.trim(), ...labels].some(containsControl)
}
function validProviderUrl(baseUrl: string): boolean {
  if (!baseUrl) return true
  try {
      const parsed = new URL(baseUrl)
      const host=parsed.hostname.toLowerCase()
      if (parsed.protocol !== "https:" || !parsed.hostname || parsed.username || parsed.password ||
          parsed.search || parsed.hash || baseUrl.length > 2048 ||
          /[\s%]/.test(parsed.host) ||
          !["", "443", "8443"].includes(parsed.port) ||
          [".local", ".localhost", ".internal", ".lan", ".home", ".onion"].some(tld=>host.endsWith(tld))) return false
      // Server performs final public-DNS/IP-range checks and guards redirects
      // and DNS rebinding; client-side URL parsing cannot establish those facts.
    return true
  } catch { return false }
}
function githubOptions(value: SourceProviderDraft): Pick<SourceProviderOptions, "installation_id" | "organization"> | null {
  const options: Pick<SourceProviderOptions, "installation_id" | "organization"> = {}
    if (value.authType === "github_app") {
      if (!/^[1-9][0-9]*$/.test(value.installationId) || !Number.isSafeInteger(Number(value.installationId))) return null
      options.installation_id = Number(value.installationId)
    }
    const org=value.organization.trim()
    if (org && !githubOrganization.test(org)) return null
    options.organization = org
  return options
}
function providerFields(value: SourceProviderDraft): Partial<SourceProviderOptions> | null {
  if (value.provider === "github") return githubOptions(value)
  if (value.provider === "gitlab") {
    const namespace=value.namespace.trim()
    if(namespace && !gitlabNamespace.test(namespace)) return null
    return { namespace }
  }
    const tenant=value.tenant.trim()
    if(tenant && !infrastructureTenant.test(tenant))return null
    return { tenant }
}
export function sourceProviderOptions(value: SourceProviderDraft): SourceProviderOptions | null {
  if (!providerAuthTypes(value.provider).includes(value.authType) || !validProviderFields(value)) return null
  const baseUrl = value.baseUrl.trim()
  if (!validProviderUrl(baseUrl)) return null
  const fields = providerFields(value)
  return fields ? { base_url: baseUrl.replace(/\/+$/, ""), display_name: value.displayName.trim(), ...fields } : null
}
