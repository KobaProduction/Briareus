import { expect, mock, test } from "bun:test"
import * as oidc from "oidc-client-ts"
import type { User, UserManagerSettings } from "oidc-client-ts"

function user(token: string, remaining = 3600): User {
  const now = Math.floor(Date.now() / 1000)
  return new oidc.User({
    access_token: token, refresh_token: "memory-refresh", token_type: "Bearer", expires_at: now + remaining,
    profile: { sub: "subject", iss: "https://identity.example.test", aud: "public-panel", exp: now + 3600, iat: now },
    userState: { returnTo: "/admin/#browser" },
  })
}

let instance: FakeManager
class FakeManager {
  stored: User | null = null
  callbackUser = user("initial-access", 20)
  callbackFailure = false
  refreshFailure = false
  refreshCalls = 0
  redirectCalls = 0
  redirectLocale = ""
  logoutCalls = 0
  loaded: Array<(value: User) => void> = []
  unloaded: Array<() => void> = []
  events = {
    addUserLoaded: (callback: (value: User) => void) => { this.loaded.push(callback) },
    addUserUnloaded: (callback: () => void) => { this.unloaded.push(callback) },
    addAccessTokenExpiring: (_callback: () => void) => {},
    addAccessTokenExpired: (_callback: () => void) => {},
  }
  constructor(readonly settings: UserManagerSettings) { instance = this }
  async clearStaleState(): Promise<void> {}
  async getUser(): Promise<User | null> { return this.stored }
  async removeUser(): Promise<void> { this.stored = null; this.unloaded.forEach(callback => callback()) }
  async signinRedirectCallback(): Promise<User> {
    if (this.callbackFailure) throw new oidc.ErrorResponse({ error: "access_denied", error_description: "private provider diagnostic" })
    this.stored = this.callbackUser
    this.loaded.forEach(callback => callback(this.callbackUser))
    return this.callbackUser
  }
  async signinSilent(): Promise<User> {
    this.refreshCalls += 1
    if (this.refreshFailure) throw new Error("Refresh rejected by ZITADEL")
    await Promise.resolve()
    this.stored = user("renewed-access")
    this.loaded.forEach(callback => callback(this.stored!))
    return this.stored
  }
  async signinRedirect(args?: { ui_locales?: string }): Promise<void> { this.redirectCalls += 1; this.redirectLocale = args?.ui_locales ?? "" }
  async signoutRedirect(): Promise<void> { this.logoutCalls += 1; await this.removeUser() }
  stopSilentRenew(): void {}
}

mock.module("oidc-client-ts", () => ({ ...oidc, UserManager: FakeManager }))

test("OIDC callback, single-flight renewal, rejected refresh and logout never create a local session or redirect loop", async () => {
  const originalFetch = globalThis.fetch
  const originalWindow = globalThis.window
  const location = new URL("https://panel.example.test/admin/?code=authorization-code&state=transaction")
  const events: string[] = []
  const fakeWindow = {
    location,
    sessionStorage: new oidc.InMemoryWebStorage(),
    history: { replaceState: (_state: unknown, _title: string, path: string) => {
      const target = new URL(path, location.origin)
      location.pathname = target.pathname; location.search = target.search; location.hash = target.hash
    } },
    dispatchEvent: (event: Event) => { events.push(event.type); return true },
  }
  globalThis.window = fakeWindow as unknown as Window & typeof globalThis
  globalThis.fetch = mock(async (_input: RequestInfo | URL, init?: RequestInit) => {
    expect(init?.credentials).toBe("omit")
    return Response.json({
      issuer: "https://identity.example.test", client_id: "public-panel", redirect_uri: "https://panel.example.test/admin/",
      post_logout_redirect_uri: "https://panel.example.test/admin/", scope: "openid profile offline_access", audience: "project",
    })
  }) as typeof fetch
  try {
    const identity = await import("../src/shared/auth/identity")
    expect(await identity.initializeIdentity()).toBe(true)
    expect(location.search).toBe("")
    expect(location.hash).toBe("#browser")
    const tokens = await Promise.all([identity.accessToken(), identity.accessToken()])
    expect(tokens).toEqual(["renewed-access", "renewed-access"])
    expect(instance.refreshCalls).toBe(1)
    expect(events).toContain("briareus:token-renewed")
    expect((await identity.authorizationHeaders()).get("Authorization")).toBe("Bearer renewed-access")
    expect(await identity.websocketProtocols()).toEqual(["briareus.v1", "bearer.renewed-access"])

    instance.stored!.expires_in = 1
    instance.refreshFailure = true
    expect(await identity.accessToken()).toBeNull()
    expect(instance.stored).toBeNull()
    expect(instance.redirectCalls).toBe(0)
    expect(events).toContain("briareus:auth-expired")
    expect(await identity.initializeIdentity()).toBe(false)

    location.search = "?error=access_denied&state=failed"
    instance.callbackFailure = true
    await expect(identity.initializeIdentity()).rejects.toBeInstanceOf(identity.IdentityCallbackError)
    expect(location.search).toBe("")
    expect(instance.redirectCalls).toBe(0)
    await identity.signIn("ru")
    expect(instance.redirectCalls).toBe(1)
    expect(instance.redirectLocale).toBe("ru")
    await identity.signIn("en")
    expect(instance.redirectLocale).toBe("en")
    await identity.signOut()
    expect(instance.logoutCalls).toBe(1)
    expect(await identity.accessToken()).toBeNull()
  } finally {
    globalThis.fetch = originalFetch
    globalThis.window = originalWindow
  }
})
