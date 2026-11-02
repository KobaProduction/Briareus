import { requireRecord } from "@/shared/lib/transport";

export interface PasswordPolicy {
  length_min?: number;
  length_max?: number;
  include_lower_case?: number;
  include_upper_case?: number;
  include_digits?: number;
  include_special?: number;
}
export interface PasswordSetupCode {
  user_id: string;
  code: string;
}
export type PasswordSetupRequest =
  | { path: "prepare"; body: PasswordSetupCode }
  | { path: "finish"; body: { password: string } }
  | { path: "recovery-pow" }
  | { path: "recovery-request"; body: { email: string; pow: string } };

export function passwordSetupCode(value: string): PasswordSetupCode {
  const match =
    value
      .trim()
      .match(
        /^(?:https?:\/\/[^/]+)?\/auth\/v1\/users\/([A-Za-z0-9]{24})\/reset\/([A-Za-z0-9]{64})(?:\?type=[^#]*)?$/,
      ) || value.trim().match(/^([A-Za-z0-9]{24}):([A-Za-z0-9]{64})$/);
  if (!match?.[1] || !match[2]) throw new Error("SETUP_CODE_INVALID_OR_EXPIRED");
  return { user_id: match[1], code: match[2] };
}
export function passwordSetupPolicy(value: unknown): PasswordPolicy {
  const row = requireRecord(value),
    result: PasswordPolicy = {};
  for (const key of [
    "length_min",
    "length_max",
    "include_lower_case",
    "include_upper_case",
    "include_digits",
    "include_special",
  ] as const) {
    const count = row[key];
    if (count === null || count === undefined) continue;
    if (typeof count !== "number" || !Number.isSafeInteger(count) || count < 0)
      throw new Error("SETUP_POLICY_INVALID");
    result[key] = count;
  }
  return result;
}
