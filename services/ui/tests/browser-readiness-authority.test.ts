import { afterEach, describe, expect, it, spyOn } from "bun:test";
import { eventBus } from "../src/shared/events/bus";
import { RpcError } from "../src/shared/events/protocol";
import { createProjectBrowser } from "../src/features/project-browser/api/project-browser";

afterEach(() => spyOn(eventBus, "request").mockRestore());

function setup(alwaysDenied = false) {
  let probes = 0,
    starts = 0;
  const source = { project_uuid: "project", signal: new AbortController().signal };
  spyOn(eventBus, "request").mockImplementation(
    async <T>(
      _method: string,
      params: Record<string, unknown>,
      decode: (value: unknown) => T,
    ): Promise<T> => {
      if (params.tool === "local_browser_status") {
        probes++;
        if (alwaysDenied || probes === 1) throw new RpcError("BROWSER_PERMISSION_DENIED", true);
        return decode({ structuredContent: { running: true } });
      }
      if (params.tool !== "web_operation_start") throw new Error("Unexpected browser operation");
      starts++;
      return decode({
        structuredContent: {
          operation_id: "inventory",
          tool: "local_browser_pages",
          state: "completed",
          result: { structuredContent: { pages: [], can_reopen_closed_tab: false } },
        },
      });
    },
  );
  return {
    browser: createProjectBrowser(() => source),
    probes: () => probes,
    starts: () => starts,
  };
}

describe("fresh browser readiness authority", () => {
  it("rechecks a transient admission failure before allowing one inventory request", async () => {
    const fixture = setup();
    expect((await fixture.browser.inventory()).pages).toEqual([]);
    expect(fixture.probes()).toBe(2);
    expect(fixture.starts()).toBe(1);
  });
  it("preserves a real denial and never launches a browser effect", async () => {
    const fixture = setup(true);
    await expect(fixture.browser.inventory()).rejects.toThrow("BROWSER_PERMISSION_DENIED");
    expect(fixture.probes()).toBe(2);
    expect(fixture.starts()).toBe(0);
  });
});
