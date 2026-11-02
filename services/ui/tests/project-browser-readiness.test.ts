import { afterEach, describe, expect, it, spyOn } from "bun:test";
import { eventBus } from "../src/shared/events/bus";
import type { ProjectCommandContext } from "../src/shared/events/hand-command";
import { RpcError } from "../src/shared/events/protocol";
import { createProjectBrowser } from "../src/features/project-browser/api/project-browser";
import { browserRefreshRequired } from "../src/features/project-browser/model/browser-refresh";

afterEach(() => {
  spyOn(eventBus, "request").mockRestore();
});

function context(controller: AbortController): ProjectCommandContext {
  return {
    project_uuid: "project",
    signal: controller.signal,
  };
}

describe("browser preparation before native effects", () => {
  it("does not retry access failures or send native effects", async () => {
    const controller = new AbortController();
    const current = context(controller);
    const tools: unknown[] = [];
    spyOn(eventBus, "request").mockImplementation(
      async <T>(
        _method: string,
        parameters: Record<string, unknown>,
        _decode: (value: unknown) => T,
      ): Promise<T> => {
        tools.push(parameters.tool);
        throw new RpcError("ACCESS_DENIED", false);
      },
    );
    await expect(
      createProjectBrowser(() => current).open("https://example.com", ""),
    ).rejects.toThrow("ACCESS_DENIED");
    expect(tools).toEqual(["local_browser_status"]);
  });
  it("polls read-only status and starts the requested effect exactly once", async () => {
    const controller = new AbortController();
    const current = context(controller);
    const tools: string[] = [];
    let probes = 0;
    const ownRequests = new Set<string>();
    spyOn(eventBus, "request").mockImplementation(
      async <T>(
        _method: string,
        parameters: Record<string, unknown>,
        decode: (value: unknown) => T,
      ): Promise<T> => {
        const operationId = parameters.operation_uuid;
        if (typeof operationId !== "string") throw new Error("Operation ID required");
        expect(ownRequests.has(operationId)).toBe(true);
        expect(
          browserRefreshRequired(
            {
              topic: "browser.runtime",
              type: "operation.completed",
              occurredAt: "2026-10-30T00:00:00Z",
              data: {
                project_id: "project",
                operation_id: operationId,
                tool: String(parameters.tool),
                status: "completed",
              },
            },
            "project",
            ownRequests,
          ),
        ).toBe(false);
        expect(parameters.project_uuid).toBe("project");
        expect("agent_session_uuid" in parameters).toBe(false);
        expect("expected_grant_revision" in parameters).toBe(false);
        const tool = parameters.tool;
        if (typeof tool !== "string") throw new Error("Tool required");
        tools.push(tool);
        if (tool === "local_browser_status") {
          if (++probes === 1) throw new RpcError("BROWSER_PREPARING", false);
          return decode({ structuredContent: { result: { running: probes > 2 } } });
        }
        if (tool !== "web_operation_start") throw new Error("Unexpected effect replay or poll");
        return decode({
          structuredContent: {
            operation_id: "operation",
            tool: "local_browser_open",
            state: "completed",
            result: {
              structuredContent: { page_id: "page", url: "https://example.com", title: "Example" },
            },
          },
        });
      },
    );
    const result = await createProjectBrowser(
      () => current,
      (id) => ownRequests.add(id),
    ).open("https://example.com", "");
    expect(result.page_id).toBe("page");
    expect(tools).toEqual([
      "local_browser_status",
      "local_browser_status",
      "local_browser_status",
      "web_operation_start",
    ]);
  });

  it("does not dispatch an effect when authority changes during the readiness probe", async () => {
    const controller = new AbortController();
    const current = context(controller);
    const tools: unknown[] = [];
    spyOn(eventBus, "request").mockImplementation(
      async <T>(
        _method: string,
        parameters: Record<string, unknown>,
        decode: (value: unknown) => T,
      ): Promise<T> => {
        tools.push(parameters.tool);
        controller.abort();
        return decode({ structuredContent: { running: true } });
      },
    );
    await expect(
      createProjectBrowser(() => current).open("https://example.com", ""),
    ).rejects.toThrow("Рабочая область изменена");
    expect(tools).toEqual(["local_browser_status"]);
  });
});
