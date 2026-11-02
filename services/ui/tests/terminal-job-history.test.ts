import { describe, expect, it } from "bun:test";
import { effectScope, reactive } from "vue";
import { decodeJobHistory } from "../src/features/terminal/api/job-history";
import type { TerminalJobHistory } from "../src/features/terminal/model/job-history";
import type { TerminalJobStatus } from "../src/features/terminal/model/terminal-result";
import { useJobHistory } from "../src/features/terminal/model/use-job-history";

function job(id = "a".repeat(32)): TerminalJobStatus {
  return {
    job_id: id,
    workspace_id: "default",
    label: "",
    command: "pwd",
    cwd: "/project-data",
    interactive: false,
    state: "completed",
    pid: null,
    exit_code: 0,
    signal: null,
    created_at: null,
    started_at: null,
    ended_at: null,
    duration_seconds: 1,
    output_bytes: 0,
    output_truncated: false,
    timeout_seconds: null,
  };
}
function receipt(jobs: TerminalJobStatus[]) {
  return {
    structuredContent: {
      jobs,
      count: jobs.length,
      total: jobs.length,
      offset: 0,
      limit: 50,
      truncated: false,
    },
  };
}

describe("human terminal job history", () => {
  it("validates the native job list and rejects foreign workspace or duplicate jobs", () => {
    expect(decodeJobHistory(receipt([job()])).jobs[0]?.state).toBe("completed");
    expect(() => decodeJobHistory(receipt([{ ...job(), workspace_id: "other" }]))).toThrow();
    expect(() => decodeJobHistory(receipt([job(), job()]))).toThrow();
    const wrong = receipt([job()]);
    wrong.structuredContent.count = 0;
    expect(() => decodeJobHistory(wrong)).toThrow();
  });

  it("drops a late result from another project without disturbing a newer read", async () => {
    const scope = effectScope(),
      state = reactive({ project: "one", enabled: true });
    let resolveOld: (value: TerminalJobHistory) => void = () => {
      throw new Error("Read not started");
    };
    let firstSignal: AbortSignal | undefined;
    const model = scope.run(() =>
      useJobHistory(
        {
          project: () => state.project,
          identity: () => state.project,
          enabled: () => state.enabled,
        },
        async (project, signal) => {
          if (project === "two") return { jobs: [job("b".repeat(32))], total: 1, truncated: false };
          firstSignal = signal;
          return new Promise<TerminalJobHistory>((resolve) => {
            resolveOld = resolve;
          });
        },
      ),
    );
    if (!model) throw new Error("History model missing");
    const old = model.refreshJobs();
    state.project = "two";
    expect(firstSignal?.aborted).toBe(true);
    await model.refreshJobs();
    resolveOld({ jobs: [job()], total: 1, truncated: false });
    await old;
    expect(model.jobs.value.map((row) => row.job_id)).toEqual(["b".repeat(32)]);
    expect(model.jobsLoading.value).toBe(false);
    state.enabled = false;
    expect(model.jobs.value).toEqual([]);
    scope.stop();
  });

  it("does not request history without project permission or after disposal", async () => {
    let calls = 0;
    const state = reactive({ enabled: false });
    const scope = effectScope();
    const model = scope.run(() =>
      useJobHistory(
        {
          project: () => "project",
          identity: () => "identity",
          enabled: () => state.enabled,
        },
        async () => {
          ++calls;
          return { jobs: [], total: 0, truncated: false };
        },
      ),
    );
    if (!model) throw new Error("History model missing");
    await model.refreshJobs();
    expect(calls).toBe(0);
    scope.stop();
    state.enabled = true;
    await model.refreshJobs();
    expect(calls).toBe(0);
  });
});
