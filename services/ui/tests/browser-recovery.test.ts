import { afterEach, describe, expect, it, spyOn } from "bun:test";
import { eventBus } from "../src/shared/events/bus";
import { createProjectBrowser } from "../src/features/project-browser/api/project-browser";

afterEach(() => spyOn(eventBus, "request").mockRestore());

function oldOperation() {
  let statuses = 0;
  const tools: string[] = [];
  const starts: string[] = [];
  spyOn(eventBus, "request").mockImplementation(
    async <T>(
      _method: string,
      parameters: Record<string, unknown>,
      decode: (value: unknown) => T,
    ): Promise<T> => {
      const tool = parameters.tool;
      if (typeof tool !== "string") throw new Error("Tool required");
      tools.push(tool);
      if (tool === "local_browser_status") {
        statuses++;
        return decode({
          structuredContent: {
            result:
              statuses === 1
                ? {
                    running: false,
                    pending: { operation_id: "existing-operation", tool: "local_browser_open" },
                  }
                : { running: true },
          },
        });
      }
      if (tool === "web_operation_poll") {
        expect(parameters.arguments).toEqual({
          operation_id: "existing-operation",
          tool: "local_browser_open",
        });
        return decode({
          structuredContent: {
            operation_id: "existing-operation",
            tool: "local_browser_open",
            state: "completed",
            result: {},
          },
        });
      }
      if (tool !== "web_operation_start") throw new Error("Unexpected command");
      const args = parameters.arguments;
      if (!args || typeof args !== "object" || !("tool" in args) || typeof args.tool !== "string")
        throw new Error("Original tool required");
      starts.push(args.tool);
      return decode({
        structuredContent: {
          operation_id: "fresh-read",
          tool: args.tool,
          state: "completed",
          result: { structuredContent: { pages: [], can_reopen_closed_tab: false } },
        },
      });
    },
  );
  return { tools, starts };
}

describe("browser reload recovery", () => {
  it("resumes the existing handle before reading tabs and never replays its mutation", async () => {
    const observed = oldOperation();
    const controller = new AbortController();
    const browser = createProjectBrowser(() => ({
      project_uuid: "project",
      signal: controller.signal,
    }));
    expect((await browser.inventory()).pages).toEqual([]);
    expect(observed.starts).toEqual(["local_browser_pages"]);
    expect(observed.tools.slice(0, 3)).toEqual([
      "local_browser_status",
      "web_operation_poll",
      "local_browser_status",
    ]);
  });
  it("refreshes the view before allowing coordinates from a pre-recovery frame", async () => {
    const observed = oldOperation();
    const controller = new AbortController();
    let refreshes = 0;
    const browser = createProjectBrowser(
      () => ({ project_uuid: "project", signal: controller.signal }),
      () => undefined,
      () => {
        refreshes++;
      },
    );
    await expect(
      browser.input("page", [{ kind: "click", x: 1, y: 1, button: "left", click_count: 1 }]),
    ).rejects.toThrow("Предыдущая операция завершена");
    expect(observed.starts).toEqual([]);
    expect(refreshes).toBe(1);
  });
});
