/** Native MCP/RPC boundary. Only the supplied decoded receipt leaves this adapter. */
import { mcpValue } from "../lib/transport";
import { eventBus } from "./bus";
import type { ReplyDecoder } from "./protocol";

export interface ProjectCommandContext {
  project_uuid: string;
  signal: AbortSignal;
}

export type ProjectCommandSource = () => ProjectCommandContext | null;

export interface HandCommandContext extends ProjectCommandContext {
  agent_session_uuid: string;
  expected_grant_revision: number;
}

export type HandCommandSource = () => HandCommandContext | null;

export function sameProjectContext(
  source: ProjectCommandSource,
  original: ProjectCommandContext,
): boolean {
  const current = source();
  return (
    !original.signal.aborted &&
    current !== null &&
    current.signal === original.signal &&
    current.project_uuid === original.project_uuid
  );
}

export function sameHandContext(source: HandCommandSource, original: HandCommandContext): boolean {
  const current = source();
  return (
    !original.signal.aborted &&
    current !== null &&
    current.signal === original.signal &&
    current.project_uuid === original.project_uuid &&
    current.agent_session_uuid === original.agent_session_uuid &&
    current.expected_grant_revision === original.expected_grant_revision
  );
}

export function callHand<T>(
  method: "analysis.command",
  context: ProjectCommandContext,
  tool: string,
  argumentsValue: Record<string, unknown>,
  decode: ReplyDecoder<T>,
  operationUuid: string = crypto.randomUUID(),
): Promise<T> {
  return eventBus.request(
    method,
    {
      project_uuid: context.project_uuid,
      operation_uuid: operationUuid,
      tool,
      arguments: argumentsValue,
    },
    (raw) => mcpValue(raw, decode),
    context.signal,
  );
}

export function callBrowser<T>(
  context: ProjectCommandContext,
  tool: string,
  argumentsValue: Record<string, unknown>,
  decode: ReplyDecoder<T>,
  operationUuid: string = crypto.randomUUID(),
): Promise<T> {
  return eventBus.request(
    "browser.command",
    {
      project_uuid: context.project_uuid,
      operation_uuid: operationUuid,
      tool,
      arguments: argumentsValue,
    },
    (raw) => mcpValue(raw, decode),
    context.signal,
  );
}
