import { CONTROL_PANEL_AUTH_API } from "@/shared/config";
import { readBoundedJsonResponse } from "@/shared/lib/transport";
import {
  type RauthyLogoutResult,
  type RauthyPanelState,
  validConfiguration,
  verifiedIdentity,
} from "../model/session";

const CONFIG = `${CONTROL_PANEL_AUTH_API}/config`;
const SESSION = `${CONTROL_PANEL_AUTH_API}/session`;
const LOGOUT = `${CONTROL_PANEL_AUTH_API}/logout`;

/** 200 config is only OIDC discovery, 401 session is signed-out, never a User grant. */
export async function readRauthyPanelState(signal: AbortSignal): Promise<RauthyPanelState> {
  const request: RequestInit = {
    method: "GET",
    signal,
    credentials: "same-origin",
    mode: "same-origin",
    redirect: "error",
    referrerPolicy: "no-referrer",
    cache: "no-store",
    headers: { Accept: "application/json" },
  };
  try {
    // The browser session is the only identity proof. Configuration does not
    // imply logged-in state, and a malformed 200 must never become a principal.
    const session = await fetch(SESSION, request);
    if (signal.aborted) return { kind: "unavailable", reason: "network" };
    if (session.status === 403) return { kind: "unavailable", reason: "forbidden" };
    // HTTP401 is the authoritative absence of an OIDC browser session:
    // do not fetch discovery metadata or imply a configured IdP is a login.
    if (session.status === 401) return { kind: "signed_out" };
    if (session.status !== 200) {
      return { kind: "unavailable", reason: "session_unavailable" };
    }
    const config = await fetch(CONFIG, request);
    if (signal.aborted) return { kind: "unavailable", reason: "network" };
    if (!config.ok) return { kind: "unavailable", reason: "provider_unavailable" };
    const metadata = validConfiguration(await readBoundedJsonResponse(config, signal, 8192));
    if (signal.aborted) return { kind: "unavailable", reason: "network" };
    if (!metadata) return { kind: "unavailable", reason: "invalid_response" };
    const identity = verifiedIdentity(
      await readBoundedJsonResponse(session, signal, 8192),
      metadata,
    );
    if (signal.aborted) return { kind: "unavailable", reason: "network" };
    return identity
      ? { kind: "signed_in", identity }
      : { kind: "unavailable", reason: "invalid_response" };
  } catch {
    return { kind: "unavailable", reason: "network" };
  }
}

/** Only a server 204 is proof that private Valkey session deletion committed. */
export async function signOutRauthyPanel(signal: AbortSignal): Promise<RauthyLogoutResult> {
  if (signal.aborted) return { kind: "unavailable" };
  try {
    const response = await fetch(LOGOUT, {
      method: "POST",
      signal,
      credentials: "same-origin",
      mode: "same-origin",
      redirect: "error",
      referrerPolicy: "no-referrer",
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    // A late HTTP204 after an aborted POST is NOT proof that the browser
    // completed logout; owner removal may have raced with a reissued cookie.
    if (signal.aborted) return { kind: "uncertain" };
    if (response.status === 204) return { kind: "revoked" };
    if (response.status === 403) return { kind: "forbidden" };
    if (response.status === 503) return { kind: "unavailable" };
    return { kind: "uncertain" };
  } catch {
    return { kind: "uncertain" };
  }
}
