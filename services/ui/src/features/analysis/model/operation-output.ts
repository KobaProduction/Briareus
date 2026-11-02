import type { McpOperation } from "@/shared/lib/transport";

export function analysisOperationOutput(operation: McpOperation<string>): string {
  const status = JSON.stringify(
    {
      operation_id: operation.operation_id,
      tool: operation.tool,
      state: operation.state,
    },
    null,
    2,
  );
  if (operation.state === "completed") return `${status}\n${operation.result}`;
  if (operation.state === "failed") return `${status}\n${operation.error}`;
  return status;
}
