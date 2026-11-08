import type { McpServiceDescriptor } from "./types"

export interface ServiceGroup {
  id: string
  services: McpServiceDescriptor[]
}
const GROUP_ORDER = [
  "svc",
  "web",
  "server",
  "observability",
  "infrastructure",
  "analysis",
]
export function groupedServices(
  services: McpServiceDescriptor[],
  showUnavailable: boolean,
): ServiceGroup[] {
  const groups = new Map<string, McpServiceDescriptor[]>()
  for (const service of services) {
    if (!service.connected && !showUnavailable) continue
    const group = groups.get(service.group) ?? []
    group.push(service)
    groups.set(service.group, group)
  }
  return [...groups]
    .sort(([a], [b]) => {
      const left = GROUP_ORDER.indexOf(a),
        right = GROUP_ORDER.indexOf(b)
      return (
        (left < 0 ? GROUP_ORDER.length : left) -
          (right < 0 ? GROUP_ORDER.length : right) || a.localeCompare(b)
      )
    })
    .map(([id, services]) => ({ id, services }))
}
export function servicePath(id: string): string {
  return id === "server" ? "server/files" : `services/${encodeURIComponent(id)}`
}
export function serviceConnectionUrl(
  path: string,
  origin: string,
): string | null {
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("\\"))
    return null
  const url = new URL(path, origin)
  return url.origin === origin && !url.search && !url.hash ? url.href : null
}
export function serviceForRoute(path: string): string | null {
  const [root, child] = path.split("/")
  if (root === "services" && child) {
    try {
      return decodeURIComponent(child)
    } catch {
      return null
    }
  }
  if (root === "server" || root === "files" || root === "terminal")
    return "server"
  if (root === "browser") return "playwright"
  if (root === "analysis") return "analysis"
  if (root === "git" && (child === "github" || child === "gitlab")) return child
  if (root === "observability" && (child === "signoz" || child === "coolify"))
    return child
  return null
}
