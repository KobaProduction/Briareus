import type {
  BrowserConfiguration,
  ModuleConfiguration,
  RuntimePolicy,
  SerenaConfiguration,
} from "../model/module-configuration";
import type { RuntimePolicyKey, RuntimePolicyValues } from "../model/node-commands";
import type { NodeRuntimePolicy } from "../model/node-replies";
import {
  replyBoolean,
  replyChoice,
  replyNumber,
  replyRecord,
  replyString,
  replyUuid,
} from "./node-reply-values";
const policyKeys = [
  "execution_timeout_seconds",
  "web_max_tabs",
  "web_tab_idle_seconds",
  "terminal_idle_seconds",
] as const;
function policyValue(value: unknown, key: RuntimePolicyKey): number | null {
  if (value === null) return null;
  const number = replyNumber(
    value,
    Number.MIN_VALUE,
    key === "web_max_tabs" ? 2 ** 32 - 1 : Number.MAX_VALUE,
    key === "web_max_tabs",
  );
  return number;
}
export function decodeEffectivePolicy(value: unknown): RuntimePolicy {
  const policy = replyRecord(value);
  return {
    execution_timeout_seconds: policyValue(
      policy.execution_timeout_seconds,
      "execution_timeout_seconds",
    ),
    web_max_tabs: policyValue(policy.web_max_tabs, "web_max_tabs"),
    web_tab_idle_seconds: policyValue(policy.web_tab_idle_seconds, "web_tab_idle_seconds"),
    terminal_idle_seconds: policyValue(policy.terminal_idle_seconds, "terminal_idle_seconds"),
  };
}
function policyOverrides(value: unknown): RuntimePolicyValues {
  const input = replyRecord(value),
    overrides: RuntimePolicyValues = {};
  if (Object.keys(input).some((key) => !policyKeys.some((allowed) => allowed === key)))
    throw Error("NODE_RESPONSE_INVALID");
  for (const key of policyKeys)
    if (Object.hasOwn(input, key)) overrides[key] = policyValue(input[key], key);
  return overrides;
}
export function decodeRuntimePolicy(
  value: unknown,
  scope: "node" | "server",
  nodeId: string,
): { runtime_policy: NodeRuntimePolicy } {
  const input = replyRecord(replyRecord(value).runtime_policy),
    sources = replyRecord(input.sources);
  const policy: NodeRuntimePolicy = {
    scope: replyChoice(input.scope, ["node", "server"]),
    node_uuid: input.node_uuid === null ? null : replyUuid(input.node_uuid),
    sequence: replyNumber(input.sequence, 0),
    overrides: policyOverrides(input.overrides),
    effective: decodeEffectivePolicy(input.effective),
    sources: {
      execution_timeout_seconds: replyChoice(sources.execution_timeout_seconds, [
        "default",
        "node",
        "server",
      ]),
      web_max_tabs: replyChoice(sources.web_max_tabs, ["default", "node", "server"]),
      web_tab_idle_seconds: replyChoice(sources.web_tab_idle_seconds, [
        "default",
        "node",
        "server",
      ]),
      terminal_idle_seconds: replyChoice(sources.terminal_idle_seconds, [
        "default",
        "node",
        "server",
      ]),
    },
    applies_on: replyChoice(input.applies_on, ["placement_update"]),
  };
  if (policy.scope !== scope || policy.node_uuid !== (scope === "node" ? nodeId : null))
    throw Error("NODE_RESPONSE_SCOPE_INVALID");
  return { runtime_policy: policy };
}
function browserConfiguration(value: unknown): BrowserConfiguration {
  const browser = replyRecord(value);
  return {
    external_enabled: replyBoolean(browser.external_enabled),
    external_mcp_url: replyString(browser.external_mcp_url),
    call_timeout_seconds:
      browser.call_timeout_seconds === null ? null : replyNumber(browser.call_timeout_seconds, 1),
    auto_disconnect_enabled: replyBoolean(browser.auto_disconnect_enabled),
    idle_timeout_seconds: replyNumber(browser.idle_timeout_seconds, 30, 86400),
    profile_dir_name: replyString(browser.profile_dir_name, 128),
    developer_access_enabled: replyBoolean(browser.developer_access_enabled),
  };
}
function serenaConfiguration(value: unknown): SerenaConfiguration {
  const serena = replyRecord(value);
  return {
    project_path: replyString(serena.project_path, 512),
    language_backend: replyChoice(serena.language_backend, ["LSP"]),
  };
}
/** Materialize only present fields: omitted/null configuration retains the
 * provider's update semantics instead of inserting client defaults. */
export function decodeModuleConfiguration(value: unknown): ModuleConfiguration | null {
  if (value === null || value === undefined) return null;
  const input = replyRecord(value),
    configuration: ModuleConfiguration = {};
  if (Object.hasOwn(input, "runtime_policy"))
    configuration.runtime_policy =
      input.runtime_policy === null ? null : decodeEffectivePolicy(input.runtime_policy);
  if (Object.hasOwn(input, "network"))
    configuration.network =
      input.network === null
        ? null
        : { profile: replyChoice(replyRecord(input.network).profile, ["public"]) };
  if (Object.hasOwn(input, "browser"))
    configuration.browser = input.browser === null ? null : browserConfiguration(input.browser);
  if (Object.hasOwn(input, "serena"))
    configuration.serena = input.serena === null ? null : serenaConfiguration(input.serena);
  return configuration;
}
