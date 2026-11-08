import { UserManager, type User } from "oidc-client-ts"
import { identityConfig, identitySettings, bearerProtocols, returnPath } from "./config"
import { IdentityCallbackError, IdentityError } from "./errors"
import { supportedLocale } from "../lib/locale"
import { identityStorage, IDENTITY_STORAGE_KEY } from "./storage"
import { withBrowserLock } from "../state/persistence"

export { IdentityCallbackError } from "./errors"

let managerPromise: Promise<UserManager> | null = null
let currentUser: User | null = null
let renewal: Promise<User | null> | null = null

function rememberUser(user: User | null): void {
  currentUser = user
}

export interface IdentityAccount {
  displayName: string
  locale: "ru" | "en" | null
}

export function identityAccount(): IdentityAccount | null {
  if (!currentUser || currentUser.expired) return null
  return {
    displayName: currentUser.profile.name ?? currentUser.profile.preferred_username ?? "",
    locale: supportedLocale(currentUser.profile.locale),
  }
}

function expired(): void {
  rememberUser(null)
  window.dispatchEvent(new CustomEvent("briareus:auth-expired"))
}

async function createManager(): Promise<UserManager> {
  let response: Response
  try {
    response = await fetch("/api/identity/config", { credentials: "omit" })
  } catch (cause) {
    throw new IdentityError("providerUnavailable", cause)
  }
  if (!response.ok) throw new IdentityError(response.status >= 500 ? "providerUnavailable" : "configuration")
  let config
  try {
    config = identityConfig(await response.json() as unknown, window.location.origin)
  } catch (cause) {
    throw new IdentityError("configuration", cause)
  }
  const storage = identityStorage()
  const manager = new UserManager(identitySettings(config, storage.transactions, storage.users))
  manager.events.addUserLoaded((user) => {
    const changed = currentUser !== null && currentUser.access_token !== user.access_token
    rememberUser(user)
    if (changed) window.dispatchEvent(new CustomEvent("briareus:token-renewed"))
  })
  manager.events.addUserUnloaded(expired)
  manager.events.addAccessTokenExpiring(() => { if (currentUser?.refresh_token) void renew(manager) })
  manager.events.addAccessTokenExpired(expired)
  window.addEventListener("storage", event => {
    if (event.key !== IDENTITY_STORAGE_KEY && event.key !== null) return
    void synchronizeUser(manager).catch(() => manager.removeUser())
  })
  return manager
}

async function synchronizeUser(manager: UserManager): Promise<User | null> {
  const previous = currentUser
  let user: User | null
  try { user = await manager.getUser() }
  catch { await manager.removeUser(); return null }
  rememberUser(user)
  if (previous && !user) expired()
  else if (previous && user && previous.profile.sub !== user.profile.sub) {
    window.dispatchEvent(new CustomEvent("briareus:account-changed"))
  } else if (previous && user && previous.access_token !== user.access_token) {
    window.dispatchEvent(new CustomEvent("briareus:token-renewed"))
  }
  return user
}

function getManager(): Promise<UserManager> {
  if (!managerPromise) {
    managerPromise = createManager().catch((error: unknown) => {
      managerPromise = null
      throw error
    })
  }
  return managerPromise
}

async function renew(manager: UserManager): Promise<User | null> {
  if (renewal) return renewal
  renewal = withBrowserLock(`oidc-refresh:${manager.settings.authority}:${manager.settings.client_id}`, async () => {
    const user = await synchronizeUser(manager)
    if (user && !user.expired && (user.expires_in ?? 0) > 45) return user
    if (!user?.refresh_token) { await manager.removeUser(); return null }
    return manager.signinSilent()
  }).catch(async () => {
    await manager.removeUser()
    return null
  }).finally(() => { renewal = null })
  return renewal
}

export async function initializeIdentity(): Promise<boolean> {
  const manager = await getManager()
  const parameters = new URLSearchParams(window.location.search)
  if (parameters.has("state") && (parameters.has("code") || parameters.has("error"))) {
    try {
      const user = await manager.signinRedirectCallback()
      rememberUser(user)
      window.history.replaceState(null, "", returnPath(user.state))
    } catch (error) {
      window.history.replaceState(null, "", window.location.pathname)
      await manager.removeUser()
      throw new IdentityCallbackError(error)
    }
  } else if (parameters.has("state")) {
    await manager.signoutRedirectCallback()
    window.history.replaceState(null, "", window.location.pathname)
  }
  await manager.clearStaleState()
  try { currentUser = await manager.getUser() }
  catch { await manager.removeUser(); return false }
  return Boolean(await accessToken())
}

export async function signIn(locale: "ru" | "en" = "en", selectAccount = false): Promise<void> {
  const manager = await getManager()
  await manager.clearStaleState()
  try {
    await manager.signinRedirect({
      ui_locales: locale,
      ...(selectAccount ? { prompt: "select_account" } : {}),
      state: { returnTo: window.location.pathname + window.location.hash },
    })
  } catch (cause) {
    throw new IdentityError("providerUnavailable", cause)
  }
}

export async function accessToken(): Promise<string | null> {
  if (managerPromise) await synchronizeUser(await managerPromise)
  if (!currentUser) return null
  if (currentUser.expired || (currentUser.refresh_token && (currentUser.expires_in ?? 0) <= 45)) {
    if (!managerPromise) return null
    const user = await renew(await managerPromise)
    return user && !user.expired ? user.access_token : null
  }
  return currentUser.access_token
}

export async function authorizationHeaders(initial?: HeadersInit): Promise<Headers> {
  const headers = new Headers(initial)
  const token = await accessToken()
  if (!token) throw new IdentityError("loginRequired")
  headers.set("Authorization", `Bearer ${token}`)
  return headers
}

export async function websocketProtocols(): Promise<string[]> {
  return bearerProtocols(await accessToken() ?? "")
}

export async function authenticatedSocket(url: string): Promise<WebSocket> {
  const target = new URL(url, window.location.href)
  if (target.host !== window.location.host || !["ws:", "wss:"].includes(target.protocol)) {
    throw new Error("Authenticated WebSocket must use the panel host")
  }
  if (window.location.protocol === "https:" && target.protocol !== "wss:") {
    throw new Error("Authenticated WebSocket requires TLS")
  }
  return new WebSocket(target, await websocketProtocols())
}

export async function invalidateIdentity(): Promise<void> {
  if (managerPromise) await (await managerPromise).removeUser()
  else expired()
}
