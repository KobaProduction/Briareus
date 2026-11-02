import { describe, expect, it } from "bun:test";
import type {
  TerminalCancel,
  TerminalCommand,
  TerminalCreateWorkspace,
  TerminalRead,
  TerminalStart,
} from "../src/features/terminal/model/contracts";
import { runTerminalJob } from "../src/features/terminal/model/run-job";
import type {
  TerminalJobRead,
  TerminalJobState,
  TerminalJobStatus,
  TerminalReply,
  TerminalWorkspaceCreated,
} from "../src/features/terminal/model/terminal-result";
import { RpcError } from "../src/shared/events/protocol";

const intent: TerminalStart = {
  operation_uuid: "11111111-1111-4111-8111-111111111111",
  project_uuid: "22222222-2222-4222-8222-222222222222",
  tool: "job_start",
  arguments: { workspace_id: "default", command: "pwd", interactive: false },
};
const job = "a".repeat(32);
class TerminalFixture {
  readonly commands: TerminalCommand[] = [];
  state: TerminalJobState = "completed";
  output = "";
  beforeReply: () => void = () => {};
  failed = false;
  command(command: TerminalStart | TerminalCancel): Promise<TerminalReply<TerminalJobStatus>>;
  command(command: TerminalCreateWorkspace): Promise<TerminalReply<TerminalWorkspaceCreated>>;
  command(command: TerminalRead): Promise<TerminalReply<TerminalJobRead>>;
  async command(
    command: TerminalCommand,
  ): Promise<TerminalReply<TerminalJobStatus | TerminalWorkspaceCreated | TerminalJobRead>> {
    this.commands.push(command);
    this.beforeReply();
    if (this.failed) return { kind: "failed" };
    if (command.tool === "workspace_create")
      return {
        kind: "accepted",
        receipt: { workspace_id: "default", path: "/workspace", created: true },
      };
    if (command.tool === "job_read")
      return {
        kind: "accepted",
        receipt: {
          job_id: job,
          cursor: command.arguments.cursor,
          next_cursor: this.output.length,
          output: this.output,
          total_output_bytes: this.output.length,
          state: this.state,
          eof: true,
          output_truncated: false,
        },
      };
    return {
      kind: "accepted",
      receipt: {
        job_id: job,
        workspace_id: "default",
        label: "",
        command: "pwd",
        cwd: "/workspace",
        interactive: false,
        state: "running",
        pid: 42,
        exit_code: null,
        signal: null,
        created_at: "2026-10-28T00:00:00Z",
        started_at: "2026-10-28T00:00:00Z",
        ended_at: null,
        duration_seconds: 0,
        output_bytes: 0,
        output_truncated: false,
        timeout_seconds: null,
      },
    };
  }
}
describe("Terminal exact execution intent", () => {
  it("waits for confirmed zero-dispatch preparation and sends the start only once", async () => {
    const fixture = new TerminalFixture();
    let cold = true;
    fixture.beforeReply = () => {
      if (cold) {
        cold = false;
        throw new RpcError("TERMINAL_PREPARING", false, true);
      }
    };
    await runTerminalJob(
      {
        intent,
        recovering: false,
        jobId: "",
        signal: new AbortController().signal,
        current: () => true,
        started: () => {},
        output: () => {},
      },
      fixture.command.bind(fixture),
    );
    expect(fixture.commands.map((value) => value.tool)).toEqual([
      "workspace_create",
      "workspace_create",
      "job_start",
      "job_read",
    ]);
    expect(fixture.commands[0]).toBe(fixture.commands[1]);
    expect(fixture.commands[2]).toBe(intent);
  });
  it("does not retry a workspace operation with an unknown result", async () => {
    const fixture = new TerminalFixture();
    fixture.beforeReply = () => {
      throw new RpcError("TERMINAL_OUTCOME_UNKNOWN", true, true);
    };
    await expect(
      runTerminalJob(
        {
          intent,
          recovering: false,
          jobId: "",
          signal: new AbortController().signal,
          current: () => true,
          started: () => {},
          output: () => {},
        },
        fixture.command.bind(fixture),
      ),
    ).rejects.toThrow("TERMINAL_OUTCOME_UNKNOWN");
    expect(fixture.commands.map((value) => value.tool)).toEqual(["workspace_create"]);
  });
  it("creates the workspace once, retains the exact start intent and reads the returned job", async () => {
    const fixture = new TerminalFixture();
    fixture.output = "done";
    const output: string[] = [],
      started: string[] = [];
    const result = await runTerminalJob(
      {
        intent,
        recovering: false,
        jobId: "",
        signal: new AbortController().signal,
        current: () => true,
        started: (id) => started.push(id),
        output: (text) => output.push(text),
      },
      fixture.command.bind(fixture),
    );
    expect(fixture.commands.map((command) => command.tool)).toEqual([
      "workspace_create",
      "job_start",
      "job_read",
    ]);
    expect(fixture.commands[1]).toBe(intent);
    const read = fixture.commands[2];
    if (read?.tool !== "job_read") throw new Error("expected job read");
    expect(read.arguments).toEqual({ job_id: job, cursor: 0, max_bytes: 65536, wait_seconds: 0 });
    expect(started).toEqual([job]);
    expect(output).toEqual(["", "done"]);
    expect(result).toEqual({ kind: "complete", state: "completed" });
  });
  it("never sends a start after scope invalidation during workspace creation", async () => {
    const fixture = new TerminalFixture();
    let current = true;
    fixture.beforeReply = () => {
      current = false;
    };
    const result = await runTerminalJob(
      {
        intent,
        recovering: false,
        jobId: "",
        signal: new AbortController().signal,
        current: () => current,
        started: () => {
          throw new Error("unexpected job");
        },
        output: () => {
          throw new Error("unexpected output");
        },
      },
      fixture.command.bind(fixture),
    );
    expect(result).toEqual({ kind: "superseded" });
    expect(fixture.commands.map((command) => command.tool)).toEqual(["workspace_create"]);
  });
  it("recovers a known job without issuing another start", async () => {
    const fixture = new TerminalFixture();
    fixture.state = "cancelled";
    expect(
      await runTerminalJob(
        {
          intent,
          recovering: true,
          jobId: job,
          signal: new AbortController().signal,
          current: () => true,
          started: () => {
            throw new Error("unexpected start");
          },
          output: () => {},
        },
        fixture.command.bind(fixture),
      ),
    ).toEqual({ kind: "complete", state: "cancelled" });
    expect(fixture.commands.map((command) => command.tool)).toEqual(["job_read"]);
  });
  it("replays an unknown start with the original operation instead of creating another workspace", async () => {
    const fixture = new TerminalFixture();
    await runTerminalJob(
      {
        intent,
        recovering: true,
        jobId: "",
        signal: new AbortController().signal,
        current: () => true,
        started: () => {},
        output: () => {},
      },
      fixture.command.bind(fixture),
    );
    expect(fixture.commands[0]).toBe(intent);
    expect(fixture.commands.map((command) => command.tool)).toEqual(["job_start", "job_read"]);
  });
  it("does not start a job after the workspace operation fails", async () => {
    const fixture = new TerminalFixture();
    fixture.failed = true;
    await expect(
      runTerminalJob(
        {
          intent,
          recovering: false,
          jobId: "",
          signal: new AbortController().signal,
          current: () => true,
          started: () => {
            throw new Error("unexpected start");
          },
          output: () => {},
        },
        fixture.command.bind(fixture),
      ),
    ).rejects.toThrow("TERMINAL_OPERATION_FAILED");
    expect(fixture.commands.map((command) => command.tool)).toEqual(["workspace_create"]);
  });
});
