/** Decode owner scopes before returning them to Files, Browser or Analysis views. */
import { type HandEffectScope, parseHandEffectScopes } from "../lib/hand-effect-scope";
import { recordValue } from "../lib/transport";
import { eventBus } from "./bus";

type HandResourcesMethod = "files.resources" | "browser.resources" | "analysis.resources";

export async function readHandResources(
  method: HandResourcesMethod,
  project: string,
  operations: readonly string[],
  signal: AbortSignal,
): Promise<HandEffectScope[] | null> {
  return eventBus.request(
    method,
    { project_uuid: project },
    (value) => {
      const reply = recordValue(value);
      return parseHandEffectScopes(reply?.items, operations, project);
    },
    signal,
  );
}
