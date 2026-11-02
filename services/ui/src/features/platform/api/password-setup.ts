import { CONTROL_PANEL_AUTH_API } from "@/shared/config";
import { readBoundedJsonResponse, recordValue, requireRecord } from "@/shared/lib/transport";

import {
  type PasswordPolicy,
  type PasswordSetupRequest,
  passwordSetupCode,
  passwordSetupPolicy,
} from "../model/password-setup";
import { solveRauthyPow } from "../model/rauthy-pow";

async function call<T>(
  request: PasswordSetupRequest,
  signal: AbortSignal,
  decode: (value: unknown) => T,
): Promise<T> {
  const response = await fetch(`${CONTROL_PANEL_AUTH_API}/password-setup/${request.path}`, {
    method: "POST",
    credentials: "same-origin",
    mode: "same-origin",
    redirect: "error",
    cache: "no-store",
    referrerPolicy: "no-referrer",
    signal,
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify("body" in request ? request.body : {}),
  });
  const result = requireRecord(await readBoundedJsonResponse(response, signal, 8192));
  if (!response.ok) {
    const error = recordValue(result.error);
    throw new Error(typeof error?.code === "string" ? error.code : "SETUP_PROVIDER_UNAVAILABLE");
  }
  return decode(result);
}
export async function preparePasswordSetup(
  link: string,
  signal: AbortSignal,
): Promise<PasswordPolicy> {
  return call({ path: "prepare", body: passwordSetupCode(link) }, signal, (value) =>
    passwordSetupPolicy(requireRecord(value).password_policy),
  );
}
export async function finishPasswordSetup(password: string, signal: AbortSignal): Promise<void> {
  await call({ path: "finish", body: { password } }, signal, () => undefined);
}
export async function recoverPasswordSetup(email: string, signal: AbortSignal): Promise<void> {
  const challenge = await call({ path: "recovery-pow" }, signal, (value) => {
    const row = requireRecord(value);
    if (typeof row.challenge !== "string") throw new Error("SETUP_PROVIDER_UNAVAILABLE");
    return row.challenge;
  });
  const solution = await solveRauthyPow(challenge, signal);
  if (solution.kind !== "solved") throw new Error("SETUP_PROVIDER_UNAVAILABLE");
  await call(
    { path: "recovery-request", body: { email, pow: solution.work } },
    signal,
    () => undefined,
  );
}
