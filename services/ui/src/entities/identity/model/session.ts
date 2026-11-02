/** Same-origin, server-owned Rauthy code+PKCE session; no browser OAuth tokens. */
import type { ContextIdentityWire } from "@/shared/api";

export type RauthyPanelIdentity = ContextIdentityWire & { permissions: [] };

export type RauthyFailure =
  | "provider_unavailable"
  | "session_unavailable"
  | "forbidden"
  | "invalid_response"
  | "network";

export type RauthyPanelState =
  | { kind: "unavailable"; reason: RauthyFailure }
  | { kind: "signed_out" }
  | { kind: "signed_in"; identity: RauthyPanelIdentity };

export type RauthyLogoutResult =
  | { kind: "revoked" }
  | { kind: "forbidden" | "unavailable" | "uncertain" };

export interface BrowserConfiguration {
  issuer: string;
  client_id: string;
}
function object(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
export function validConfiguration(value: unknown): BrowserConfiguration | null {
  const data = object(value);
  if (
    !data ||
    typeof data.issuer !== "string" ||
    typeof data.client_id !== "string" ||
    data.client_id.trim().length === 0
  )
    return null;
  try {
    const url = new URL(data.issuer);
    if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash)
      return null;
  } catch {
    return null;
  }
  return { issuer: data.issuer, client_id: data.client_id };
}
export function verifiedIdentity(
  value: unknown,
  trusted: BrowserConfiguration,
): RauthyPanelIdentity | null {
  const item = object(value);
  if (
    item?.authenticated !== true ||
    item.authority !== "rauthy" ||
    typeof item.subject !== "string" ||
    item.subject.length === 0 ||
    item.issuer !== trusted.issuer ||
    item.client_id !== trusted.client_id ||
    typeof item.expires_at !== "string" ||
    !/(?:Z|[+-][0-2][0-9]:[0-5][0-9])$/.test(item.expires_at) ||
    !Number.isFinite(Date.parse(item.expires_at)) ||
    Date.parse(item.expires_at) <= Date.now() ||
    item.platform_membership_verified !== false ||
    !Array.isArray(item.permissions) ||
    item.permissions.length !== 0
  )
    return null;
  return {
    authenticated: true,
    authority: "rauthy",
    subject: item.subject,
    issuer: item.issuer,
    client_id: item.client_id,
    expires_at: item.expires_at,
    platform_membership_verified: false,
    permissions: [],
  };
}
