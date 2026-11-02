import type { RuntimePolicyKey } from "./node-commands";
/** Only an explicit 'none' mode may become protocol null. Numeric input must
 * remain finite when serialized, including exponent notation accepted by HTML. */
export function validRuntimePolicyValue(value: string | undefined, key: RuntimePolicyKey): boolean {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return false;
  return key !== "web_max_tabs" || (Number.isInteger(number) && number <= 2 ** 32 - 1);
}
export function runtimePolicyValue(value: string | undefined, key: RuntimePolicyKey): number {
  if (!validRuntimePolicyValue(value, key)) throw Error("RUNTIME_POLICY_VALUE_INVALID");
  return Number(value);
}
