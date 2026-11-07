import { describe, expect, test } from "bun:test"
import { InMemoryWebStorage } from "oidc-client-ts"
import { bearerProtocols, identityConfig, identitySettings, returnPath, type IdentityConfig } from "../src/shared/auth/config"

const config: IdentityConfig = {
  issuer: "https://identity.example.test",
  client_id: "public-panel",
  redirect_uri: "https://panel.example.test/auth/callback",
  post_logout_redirect_uri: "https://panel.example.test/",
  scope: "openid profile email offline_access urn:zitadel:iam:org:project:id:project:aud",
  audience: "project",
}

describe("OIDC browser authorization boundary", () => {
  test("PKCE uses a public client and keeps user/access/refresh tokens out of transaction storage", async () => {
    const transactions = new InMemoryWebStorage()
    const settings = identitySettings(config, transactions)
    expect(settings.response_type).toBe("code")
    expect(settings.disablePKCE).toBe(false)
    expect(settings.client_secret).toBeUndefined()
    expect(settings.fetchRequestCredentials).toBe("omit")
    expect(settings.automaticSilentRenew).toBe(false)
    expect(settings.userStore).toBeDefined()
    expect(settings.stateStore).toBeDefined()
    await settings.userStore!.set("current-user", JSON.stringify({ access_token: "access", refresh_token: "refresh" }))
    expect(transactions.length).toBe(0)
    await settings.stateStore!.set("transaction", JSON.stringify({ code_verifier: "ephemeral-proof" }))
    expect(transactions.key(0)).toBe("briareus.oidc.transaction.transaction")
    expect(await settings.userStore!.get("current-user")).toContain("access")
    const reloaded = identitySettings(config, transactions)
    expect(await reloaded.userStore!.get("current-user")).toBeFalsy()
    expect(await reloaded.stateStore!.remove("transaction")).toContain("ephemeral-proof")
    expect(transactions.length).toBe(0)
  })

  test("provider realm and scopes are forwarded without vendor assumptions", () => {
    const provider = { ...config, issuer: "https://identity.example.test/realms/briareus", scope: "openid profile", audience: "briareus-api" }
    const settings = identitySettings(identityConfig(provider, "https://panel.example.test"), new InMemoryWebStorage())
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
