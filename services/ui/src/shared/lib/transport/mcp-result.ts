/** MCP is transport-wide: tool errors and envelopes are independent of the Hand. */
export function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
export function requireRecord(value: unknown): Record<string, unknown> {
  const record = recordValue(value);
  if (!record) throw new Error("MCP_RESULT_INVALID");
  return record;
}
function textContents(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((entry: unknown) => {
    const content = recordValue(entry);
    return content?.type === "text" && typeof content.text === "string" ? [content.text] : [];
  });
}
function structuredValue(value: unknown): unknown {
  let current = value;
  let record = recordValue(current);
  while (record && Object.keys(record).length === 1 && "result" in record) {
    current = record.result;
    record = recordValue(current);
  }
  return current;
}
function nativeMcpValue(raw: unknown): unknown {
  const envelope = recordValue(raw);
  if (!envelope) return raw;
  const texts = textContents(envelope.content);
  if (envelope.isError) throw new Error(texts[0] || "MCP_TOOL_FAILED");
  if (envelope.structuredContent) return structuredValue(envelope.structuredContent);
  for (const text of texts) {
    try {
      const parsed: unknown = JSON.parse(text);
      return parsed;
    } catch {
      /* A text result need not contain JSON. */
    }
  }
  return raw;
}
export function mcpValue<T>(raw: unknown, decode: (value: unknown) => T): T {
  return decode(nativeMcpValue(raw));
}
interface OperationIdentity {
  operation_id: string;
  tool: string;
}
export type McpOperation<T> =
  | (OperationIdentity & { state: "completed"; result: T })
  | (OperationIdentity & { state: "failed"; error: string })
  | (OperationIdentity & { state: "running" | "interrupted" | "cancelled" });

function operationError(value: unknown): string {
  const record = recordValue(value);
  const messages = textContents(record?.content);
  const detail = JSON.stringify(value, null, 2);
  return [messages.join("\n"), detail].filter(Boolean).join("\n") || "MCP_OPERATION_FAILED";
}
export function operationValue<T>(value: unknown, decode: (value: unknown) => T): McpOperation<T> {
  const record = requireRecord(value);
  if (typeof record.operation_id !== "string" || typeof record.tool !== "string")
    throw new Error("MCP_OPERATION_INVALID");
  const identity = { operation_id: record.operation_id, tool: record.tool };
  switch (record.state) {
    case "completed":
      return { ...identity, state: record.state, result: decode(record.result) };
    case "failed":
      return { ...identity, state: record.state, error: operationError(record.result) };
    case "running":
    case "interrupted":
    case "cancelled":
      return { ...identity, state: record.state };
    default:
      throw new Error("MCP_OPERATION_INVALID");
  }
}
