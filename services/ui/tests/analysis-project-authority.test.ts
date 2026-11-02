import { afterEach, describe, expect, it, spyOn } from "bun:test";
import { createAnalysisClient } from "../src/features/analysis/api/analysis-client";
import { eventBus } from "../src/shared/events/bus";

afterEach(() => spyOn(eventBus, "request").mockRestore());

describe("project user Analysis authority", () => {
  it("drops agent selectors for operation continuation and keeps its exact id", async () => {
    const context = {
      project_uuid: "project",
      agent_session_uuid: "obsolete",
      expected_grant_revision: 9,
      signal: new AbortController().signal,
    };
    spyOn(eventBus, "request").mockImplementation(
      async <T>(
        method: string,
        parameters: Record<string, unknown>,
        decode: (value: unknown) => T,
      ): Promise<T> => {
        expect(method).toBe("analysis.command");
        expect(parameters).not.toHaveProperty("agent_session_uuid");
        expect(parameters).not.toHaveProperty("expected_grant_revision");
        expect(parameters.project_uuid).toBe(context.project_uuid);
        expect(parameters.tool).toBe("analysis_poll");
        expect(parameters.arguments).toEqual({ operation_id: "request:original" });
        return decode({
          structuredContent: {
            operation_id: "original",
            engine: "radare2",
            tool: "list",
            state: "completed",
            result: { ok: true },
          },
        });
      },
    );
    const result = await createAnalysisClient(() => context).poll("request:original");
    expect(result.state).toBe("completed");
  });
  it("requires a selected project before contacting the runtime", async () => {
    const request = spyOn(eventBus, "request");
    expect(() => createAnalysisClient(() => null).tools("radare2")).toThrow("Выберите проект");
    expect(request).not.toHaveBeenCalled();
  });
});
