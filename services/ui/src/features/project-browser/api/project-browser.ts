import {
  browserInteraction,
  browserInventory,
  browserPreview,
  browserSnapshot,
  browserTab,
  browserViewport,
} from "@/entities/browser";
import {
  callBrowser,
  type ProjectCommandContext,
  type ProjectCommandSource,
  type ReplyDecoder,
  RpcError,
  sameProjectContext,
} from "@/shared/events";
import {
  completeMcpOperation,
  type McpOperation,
  mcpValue,
  operationValue,
  requireRecord,
} from "@/shared/lib/transport";
import type {
  BrowserPageAction,
  BrowserReadiness,
  BrowserToolCall,
  PendingBrowserOperation,
  ProjectBrowserClient,
} from "../model/browser-commands";

function browserRunning(value: unknown): BrowserReadiness {
  const status = requireRecord(value);
  if (typeof status.running !== "boolean") throw new Error("BROWSER_STATUS_INVALID");
  if (status.pending === undefined || status.pending === null)
    return { running: status.running, pending: null };
  const pending = requireRecord(status.pending);
  if (
    status.running ||
    typeof pending.operation_id !== "string" ||
    pending.operation_id.length > 128 ||
    !pending.operation_id ||
    typeof pending.tool !== "string" ||
    !/^[A-Za-z][A-Za-z0-9_.-]{0,127}$/.test(pending.tool)
  )
    throw new Error("BROWSER_PENDING_INVALID");
  return { running: false, pending: { operation_id: pending.operation_id, tool: pending.tool } };
}

export function createProjectBrowser(
  source: ProjectCommandSource,
  onRequest: (id: string) => void = () => undefined,
  onRecovered: () => void = () => undefined,
): ProjectBrowserClient {
  function request<T>(
    current: ProjectCommandContext,
    tool: string,
    args: Record<string, unknown>,
    decode: ReplyDecoder<T>,
    operationUuid: string = crypto.randomUUID(),
  ): Promise<T> {
    onRequest(operationUuid);
    return callBrowser(current, tool, args, decode, operationUuid);
  }
  function context(): ProjectCommandContext {
    const current = source();
    if (!current) throw new Error("Выберите проект с доступом к браузеру");
    return current;
  }
  async function readinessRequest(current: ProjectCommandContext): Promise<BrowserReadiness> {
    try {
      return await request(current, "local_browser_status", {}, browserRunning);
    } catch (error) {
      if (error instanceof RpcError && error.message === "BROWSER_PREPARING")
        return { running: false, pending: null };
      throw error;
    }
  }
  async function running(current: ProjectCommandContext): Promise<BrowserReadiness> {
    try {
      return await readinessRequest(current);
    } catch (error) {
      if (
        error instanceof RpcError &&
        error.message === "BROWSER_PERMISSION_DENIED" &&
        sameProjectContext(source, current)
      ) {
        // Readiness is safe to repeat with fresh Core evidence after a cold
        // route transition. Mutations are never retried; a second denial fails.
        return readinessRequest(current);
      }
      throw error;
    }
  }
  async function recoverPending(
    current: ProjectCommandContext,
    pending: PendingBrowserOperation,
  ): Promise<void> {
    const initial: McpOperation<void> = { ...pending, state: "running" };
    const completed = await completeMcpOperation(initial, {
      current: () => sameProjectContext(source, current),
      wait: () => new Promise((resolve) => setTimeout(resolve, 1500)),
      poll: (id) =>
        request(
          current,
          "web_operation_poll",
          {
            operation_id: id,
            tool: pending.tool,
          },
          (value) => operationValue(value, () => undefined),
        ),
      progress: () => undefined,
    });
    if (!completed) throw new Error("Рабочая область изменена");
    if (completed.state === "failed") {
      onRecovered();
      throw new Error(completed.error);
    }
  }

  async function ready(current: ProjectCommandContext): Promise<boolean> {
    let recovered = false;
    while (sameProjectContext(source, current)) {
      const prepared = await running(current);
      if (!sameProjectContext(source, current)) break;
      if (prepared.pending) {
        await recoverPending(current, prepared.pending);
        recovered = true;
        continue;
      }
      if (prepared.running) return recovered;
      await new Promise<void>((resolve) => setTimeout(resolve, 1500));
    }
    throw new Error("Рабочая область изменена");
  }
  function requireFreshView(recovered: boolean, tool: BrowserToolCall["tool"]) {
    if (
      !recovered ||
      ["local_browser_pages", "local_browser_snapshot", "local_browser_preview"].includes(tool)
    )
      return;
    onRecovered();
    throw new Error(
      "Предыдущая операция завершена. Вид страницы обновляется; повторите действие после обновления.",
    );
  }

  async function effect<T>(call: BrowserToolCall, decode: ReplyDecoder<T>): Promise<T> {
    const current = context();
    const recovered = await ready(current);
    requireFreshView(recovered, call.tool);
    const requestId = crypto.randomUUID();
    const operation = (value: unknown) => operationValue(value, (raw) => mcpValue(raw, decode));
    const poll = (id: string) =>
      request(
        current,
        "web_operation_poll",
        {
          operation_id: id,
          tool: call.tool,
        },
        operation,
      );
    let result: McpOperation<T>;
    try {
      result = await request(
        current,
        "web_operation_start",
        {
          tool: call.tool,
          arguments: "arguments" in call ? call.arguments : {},
        },
        operation,
        requestId,
      );
    } catch (startError) {
      if (!sameProjectContext(source, current)) throw startError;
      result = await poll(`request:${requestId}`);
    }
    const completed = await completeMcpOperation(result, {
      current: () => sameProjectContext(source, current),
      wait: () => new Promise((resolve) => setTimeout(resolve, 1500)),
      poll,
      progress: () => undefined,
    });
    if (!completed) throw new Error("Рабочая область изменена");
    if (completed.state === "failed") throw new Error(completed.error);
    if (completed.state !== "completed")
      throw new Error(`Операция браузера не выполнена: ${completed.state}`);
    return completed.result;
  }
  return {
    running: async () => (await running(context())).running,
    inventory: () => effect({ tool: "local_browser_pages" }, browserInventory),
    open: (url: string, pageId: string) =>
      effect({ tool: "local_browser_open", arguments: { url, page_id: pageId } }, browserTab),
    restore: () => effect({ tool: "local_browser_reopen_closed_page" }, browserTab),
    settings: (section: "settings" | "extensions") =>
      effect({ tool: "local_browser_settings", arguments: { section } }, browserTab),
    input: (pageId, events) =>
      effect({ tool: "local_browser_input", arguments: { page_id: pageId, events } }, (value) =>
        browserInteraction(value, pageId),
      ),
    snapshot: (pageId: string) =>
      effect({ tool: "local_browser_snapshot", arguments: { page_id: pageId } }, browserSnapshot),
    preview: (pageId: string) =>
      effect({ tool: "local_browser_preview", arguments: { page_id: pageId } }, (value) =>
        browserPreview(value, pageId),
      ),
    close: (pageId: string) =>
      effect({ tool: "local_browser_close_page", arguments: { page_id: pageId } }, () => undefined),
    navigate: (tool: BrowserPageAction, pageId: string) =>
      effect({ tool, arguments: { page_id: pageId } }, () => undefined),
    viewport: (pageId: string, width: number, height: number) =>
      effect(
        { tool: "local_browser_set_viewport", arguments: { page_id: pageId, width, height } },
        browserViewport,
      ),
    click: (pageId: string, ref: string) =>
      effect({ tool: "local_browser_click", arguments: { page_id: pageId, ref } }, () => undefined),
    fill: (pageId: string, ref: string, value: string) =>
      effect(
        { tool: "local_browser_fill", arguments: { page_id: pageId, ref, value } },
        () => undefined,
      ),
  };
}
