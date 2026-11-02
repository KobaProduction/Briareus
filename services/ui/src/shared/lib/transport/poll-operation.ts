import type { McpOperation } from "./mcp-result";

export interface PollOperationOptions<T> {
  current: () => boolean;
  wait: () => Promise<void>;
  poll: (id: string) => Promise<McpOperation<T>>;
  progress: (operation: McpOperation<T>) => void;
}

/** Follow one issued handle. Polling never restarts an effect. */
export async function completeMcpOperation<T>(
  initial: McpOperation<T>,
  options: PollOperationOptions<T>,
): Promise<McpOperation<T> | null> {
  let result = initial;
  while (result.state === "running" && options.current()) {
    options.progress(result);
    await options.wait();
    if (!options.current()) return null;
    result = await options.poll(result.operation_id);
  }
  return options.current() ? result : null;
}
