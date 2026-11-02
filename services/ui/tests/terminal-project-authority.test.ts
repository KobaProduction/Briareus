import { afterEach, describe, expect, it, spyOn } from "bun:test";
import { terminalCommand } from "../src/features/terminal/api/terminal-command";
import type { TerminalCreateWorkspace } from "../src/features/terminal/model/contracts";
import { eventBus } from "../src/shared/events/bus";

afterEach(() => spyOn(eventBus, "request").mockRestore());

describe("project user Terminal authority", () => {
  it("drops obsolete agent authority before sending a human command", async () => {
    const command: TerminalCreateWorkspace & {
      agent_session_uuid: string;
      expected_grant_revision: number;
    } = {
      project_uuid: "22222222-2222-4222-8222-222222222222",
      operation_uuid: "11111111-1111-4111-8111-111111111111",
      agent_session_uuid: "obsolete",
      expected_grant_revision: 4,
      tool: "workspace_create",
      arguments: { workspace_id: "default" },
    };
    spyOn(eventBus, "request").mockImplementation(
      async <T>(
        method: string,
        parameters: Record<string, unknown>,
        decode: (value: unknown) => T,
      ): Promise<T> => {
        expect(method).toBe("terminal.command");
        expect(parameters).toEqual({
          project_uuid: command.project_uuid,
          operation_uuid: command.operation_uuid,
          tool: "workspace_create",
          arguments: { workspace_id: "default" },
        });
        return decode({
          structuredContent: {
            workspace_id: "default",
            path: "/workspace/default",
            created: true,
          },
        });
      },
    );
    const result = await terminalCommand(command);
    expect(result.kind).toBe("accepted");
  });
});
