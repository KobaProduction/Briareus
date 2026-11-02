import { validConnectionAuth, type ConnectionDraft, type GitPolicy } from "./connection-draft"

function controlCharacter(value: string): boolean {
  return [...value].some(character => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)
}
function policyNames(values: readonly string[] | undefined): boolean {
  return values === undefined || (values.length <= 64 && values.every(value =>
    Boolean(value.trim()) && value.length <= 128 && !controlCharacter(value)))
}
function validPolicy(policy: GitPolicy | undefined): boolean {
  return !policy || (policyNames(policy.protected_branches) && policyNames(policy.required_checks) && policyNames(policy.required_reviewers))
}
function validEndpoint(draft: ConnectionDraft): boolean {
  const value = draft.base_url.trim()
  if (draft.provider === "github") return value === "https://api.github.com"
  if (!value || value.length > 2048 || controlCharacter(value)) return false
  try {
    const url = new URL(value)
    return url.protocol === "https:" && Boolean(url.hostname) && !url.username && !url.password &&
      !url.search && !url.hash && !url.host.includes("%") && ["", "443", "8443"].includes(url.port)
  } catch { return false }
}
/** Browser input checks mirror bounded source fields; DNS, PEM parsing,
 * credential custody and provider authority remain with Resources. */
export function validConnectionDraft(draft: ConnectionDraft, editing: boolean): boolean {
  const name = draft.name.trim()
  if (!name || name.length > 128 || controlCharacter(name) || !validConnectionAuth(draft.provider, draft.auth_type)) return false
  if ((!draft.credential && !editing) || draft.credential.length > 32768 || draft.ca_cert_pem.length > 16384) return false
  if (draft.auth_type === "github_app" && !/^[1-9][0-9]{0,31}$/.test(draft.external_id)) return false
  return validEndpoint(draft) && validPolicy(draft.git_policy)
}
