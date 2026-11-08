import { describe, expect, test } from "bun:test"
import { createApp } from "vue"
import { createPanelPinia } from "../src/shared/state/pinia"
import { identityStorage, IDENTITY_STORAGE_KEY } from "../src/shared/auth/storage"
import { MemoryStorage } from "./browser-storage"
import { bearerProtocols, identityConfig, identitySettings, returnPath, type IdentityConfig } from "../src/shared/auth/config"
import { supportedLocale } from "../src/shared/lib/locale"

function stores() {
  const pinia = createPanelPinia()
  createApp({}).use(pinia)
  return identityStorage(pinia)
}

const config: IdentityConfig = {
  issuer: "https://identity.example.test",
  client_id: "public-panel",
  redirect_uri: "https://panel.example.test/auth/callback",
  post_logout_redirect_uri: "https://panel.example.test/",
  scope: "openid profile email offline_access urn:zitadel:iam:org:project:id:project:aud",
  audience: "project",
}

describe("OIDC browser authorization boundary", () => {
  test("profile locale accepts supported BCP47 tags and ignores absent or unsupported claims", () => {
    expect(supportedLocale("ru-RU")).toBe("ru")
    expect(supportedLocale("en_US")).toBe("en")
    for (const value of [undefined, null, 42, "", "fr-FR", "ru<script>"]) {
      expect(supportedLocale(value)).toBeNull()
    }
  })
  test("PKCE uses Pinia persistence across reloads and isolates transactions from provider users", async () => {
    const originalWindow = globalThis.window
    const storage = new MemoryStorage()
    globalThis.window = { localStorage: storage } as unknown as Window & typeof globalThis
    try {
      const first = stores()
      const settings = identitySettings(config, first.transactions, first.users)
      expect(settings.response_type).toBe("code")
      expect(settings.disablePKCE).toBe(false)
      expect(settings.client_secret).toBeUndefined()
      expect(settings.fetchRequestCredentials).toBe("omit")
      expect(settings.automaticSilentRenew).toBe(false)
      expect(settings.loadUserInfo).toBe(true)
      await settings.userStore!.set("current-user", JSON.stringify({ access_token: "test-access", refresh_token: "test-refresh" }))
      expect(await settings.stateStore!.get("current-user")).toBeNull()
      await settings.stateStore!.set("transaction", JSON.stringify({ code_verifier: "ephemeral-proof" }))
      const second = stores()
      const reloaded = identitySettings(config, second.transactions, second.users)
      expect(await reloaded.userStore!.get("current-user")).toContain("test-access")
      expect(await reloaded.stateStore!.remove("transaction")).toContain("ephemeral-proof")
      expect(await first.transactions.get("transaction")).toBeNull()
      await second.users.remove("current-user")
      expect(await first.users.get("current-user")).toBeNull()
      expect(await first.users.getAllKeys()).toEqual([])
      await first.users.set("current-user", "test-user")
      storage.removeItem(IDENTITY_STORAGE_KEY)
      expect(await first.users.get("current-user")).toBeNull()
      storage.setItem(IDENTITY_STORAGE_KEY, "invalid json")
      expect(await stores().users.get("current-user")).toBeNull()
    } finally { globalThis.window = originalWindow }
  })

  test("provider realm and scopes are forwarded without vendor assumptions", () => {
    const provider = { ...config, issuer: "https://identity.example.test/realms/briareus", scope: "openid profile", audience: "briareus-api" }
    const settings = identitySettings(identityConfig(provider, "https://panel.example.test"), stores().transactions, stores().users)
    expect(settings.authority).toBe(provider.issuer)
    expect(settings.scope).toBe("openid profile")
    expect(settings.metadata).toBeUndefined()
    expect(settings.disablePKCE).toBe(false)
  })

  test("public config rejects missing values and off-origin redirect targets", () => {
    expect(identityConfig(config, "https://panel.example.test")).toEqual(config)
    expect(() => identityConfig({ ...config, client_id: "" }, "https://panel.example.test")).toThrow()
    expect(() => identityConfig({ ...config, redirect_uri: "https://other.example.test/callback" }, "https://panel.example.test")).toThrow()
    expect(() => identityConfig({ ...config, post_logout_redirect_uri: "https://other.example.test/" }, "https://panel.example.test")).toThrow()
  })

  test("redirect restoration cannot leave the panel origin", () => {
    expect(returnPath({ returnTo: "/#browser" })).toBe("/#browser")
    for (const returnTo of ["//other.example.test", "https://other.example.test", "/\\other.example.test"]) {
      expect(returnPath({ returnTo })).toBe("/admin/")
    }
    expect(returnPath(null)).toBe("/admin/")
  })

  test("WebSocket bearer is a separate protocol and cannot inject protocol delimiters", () => {
    expect(bearerProtocols("header.payload.signature")).toEqual(["briareus.v1", "bearer.header.payload.signature"])
    for (const token of ["", "token,other", "token\r\nHeader: value", "token with spaces"]) {
      expect(() => bearerProtocols(token)).toThrow()
    }
  })
})
