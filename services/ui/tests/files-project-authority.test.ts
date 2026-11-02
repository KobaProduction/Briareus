import { afterEach, describe, expect, it, spyOn } from "bun:test";
import { createFilesClient } from "../src/features/files/api/workspace-client";
import { eventBus } from "../src/shared/events/bus";

afterEach(() => spyOn(eventBus, "request").mockRestore());

describe("project user Files authority", () => {
  it("sends project-only authority even when an old caller retains agent selectors", async () => {
    const controller = new AbortController();
    const context = {
      project_uuid: "project",
      agent_session_uuid: "obsolete-session",
      expected_grant_revision: 7,
      signal: controller.signal,
    };
    spyOn(eventBus, "request").mockImplementation(
      async <T>(
        method: string,
        parameters: Record<string, unknown>,
        decode: (value: unknown) => T,
        signal?: AbortSignal,
      ): Promise<T> => {
        expect(method).toBe("files.command");
        expect(signal).toBe(controller.signal);
        expect(parameters.project_uuid).toBe("project");
        expect(parameters.operation_uuid).toBeString();
        expect(parameters).not.toHaveProperty("agent_session_uuid");
        expect(parameters).not.toHaveProperty("expected_grant_revision");
        return decode({ structuredContent: { path: "fixture", sha256: "a".repeat(64) } });
      },
    );
    const files = createFilesClient(() => context);
    expect(await files.hash("fixture")).toEqual({ path: "fixture", sha256: "a".repeat(64) });
  });
  it("requires the current selected project before any execution request", async () => {
    const request = spyOn(eventBus, "request");
    await expect(createFilesClient(() => null).hash("fixture")).rejects.toThrow("Выберите проект");
    expect(request).not.toHaveBeenCalled();
  });
});
