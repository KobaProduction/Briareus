import { InMemoryWebStorage, WebStorageStateStore, type UserManagerSettings } from "oidc-client-ts"

export interface IdentityConfig {
  issuer: string
  client_id: string
  redirect_uri: string
  post_logout_redirect_uri: string
  scope: string
  audience: string
}

export function identityConfig(value: unknown, origin: string): IdentityConfig {
  if (!value || typeof value !== "object") throw new Error("Invalid identity configuration")
  const fields = value as Record<string, unknown>
  const names = ["issuer", "client_id", "redirect_uri", "post_logout_redirect_uri", "scope", "audience"] as const
  for (const name of names) {
    if (typeof fields[name] !== "string" || !fields[name].trim()) {
      throw new Error(`Missing identity configuration: ${name}`)
    }
  }
  const config = fields as unknown as IdentityConfig
  for (const name of ["redirect_uri", "post_logout_redirect_uri"] as const) {
    if (new URL(config[name]).origin !== origin) throw new Error("Identity redirect must use the panel origin")
  }
  return config
}

export function identitySettings(config: IdentityConfig, transactionStorage: Storage): UserManagerSettings {
  return {
    authority: config.issuer,
    client_id: config.client_id,
    redirect_uri: config.redirect_uri,
    post_logout_redirect_uri: config.post_logout_redirect_uri,
    response_type: "code",
    response_mode: "query",
    scope: config.scope,
    disablePKCE: false,
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    stateStore: new WebStorageStateStore({ store: transactionStorage, prefix: "briareus.oidc.transaction." }),
    staleStateAgeInSeconds: 600,
    automaticSilentRenew: false,
    monitorSession: false,
    loadUserInfo: false,
    fetchRequestCredentials: "omit",
  }
}

export function bearerProtocols(token: string): string[] {
  if (!token || !/^[A-Za-z0-9._~-]+$/.test(token)) throw new Error("No valid access token for WebSocket")
  return ["briareus.v1", `bearer.${token}`]
}

export function returnPath(state: unknown): string {
  if (!state || typeof state !== "object") return "/admin/"
  const path = (state as Record<string, unknown>).returnTo
  return typeof path === "string" && path.startsWith("/") && !path.startsWith("//") && !path.includes("\\")
    ? path : "/admin/"
}
