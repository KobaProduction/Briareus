import { describe, expect, it } from "bun:test";
import { effectScope, nextTick, reactive } from "vue";
import type { VerifiedPlatformContext } from "../src/entities/workspace";
import type { AnalysisClient, AnalysisInvocation } from "../src/features/analysis/model/command";
import type { AnalysisRecovery } from "../src/features/analysis/model/recovery";
import type { AnalysisTool } from "../src/features/analysis/model/tool";
import { useAnalysisWorkspace } from "../src/features/analysis/model/use-analysis-workspace";
import { RpcError } from "../src/shared/events/protocol";
import type { HandEffectScope } from "../src/shared/lib/hand-effect-scope";
import type { McpOperation } from "../src/shared/lib/transport";

class Runtime implements AnalysisClient {
  starts = 0;
  polls: string[] = [];
  startResult: () => Promise<McpOperation<string>> = async () => {
    throw new Error("Lost start reply");
  };
  pollResult: () => Promise<McpOperation<string>> = async () => {
    throw new Error("Outcome still unknown");
  };
  catalogueReads = 0;
  catalogueResult: () => Promise<AnalysisTool[]> = async () => [];
  async tools(): Promise<AnalysisTool[]> {
    this.catalogueReads++;
    return this.catalogueResult();
  }
  async start(_input: AnalysisInvocation, _id: string): Promise<McpOperation<string>> {
    this.starts++;
    return this.startResult();
  }
  async poll(id: string): Promise<McpOperation<string>> {
    this.polls.push(id);
    return this.pollResult();
  }
  async cancel(): Promise<void> {}
}
function fixture(right = true, saved = new Map<string, AnalysisRecovery>()) {
  const context: VerifiedPlatformContext = {
    authenticated: true,
    authority: "platform",
    rauthy: { issuer: "https://issuer.invalid", subject: "member" },
    user: { id: "member", role: "user", enabled: true },
    teams: [],
    projects: ["project", "other"].map((id) => ({
      id,
      owner: { kind: "user", id: "member" },
      permissions: right ? ["use_resources"] : [],
    })),
    expires_at: "2030-01-01T00:00:00Z",
  };
  const props = reactive({ context, selectedProjectId: "project" });
  const runtime = new Runtime(),
    scope = effectScope();
  const state = scope.run(() =>
    useAnalysisWorkspace(props, {
      resources: async () =>
        ["analysis_tools", "analysis_start", "analysis_poll", "analysis_cancel"].map(
          (tool): HandEffectScope => ({
            hand: "reverse",
            tool,
            action: "analysis.import",
            resource: { kind: "analysis_project", id: props.selectedProjectId },
          }),
        ),
      client: () => runtime,
      restore: (key) => saved.get(key) ?? null,
      save: (key, _project, recovery) => {
        saved.set(key, recovery);
      },
      forget: (key) => {
        saved.delete(key);
      },
    }),
  );
  if (!state) throw new Error("Expected a live analysis scope");
  return { props, runtime, scope, state, saved };
}
async function ready() {
  await nextTick();
  await Promise.resolve();
  await nextTick();
}
const completed: McpOperation<string> = {
  operation_id: "boot:original",
  tool: "list",
  state: "completed",
  result: "confirmed",
};

describe("human Analysis operation lifecycle", () => {
  it("waits for a cold catalogue without submitting an analysis effect", async () => {
    const f = fixture();
    let cold = true;
    f.runtime.catalogueResult = async () => {
      if (cold) {
        cold = false;
        throw new RpcError("ANALYSIS_PREPARING", false);
      }
      return [{ name: "list", inputProperties: [], inputSchemaText: "{}" }];
    };
    try {
      await ready();
      await f.state.tools();
      expect(f.runtime.catalogueReads).toBe(2);
      expect(f.runtime.starts).toBe(0);
      expect(f.state.catalog.value.map((item) => item.name)).toEqual(["list"]);
    } finally {
      f.scope.stop();
    }
  });
  it("retains an uncertain request and resumes reading without another start", async () => {
    const f = fixture();
    try {
      await ready();
      expect(f.state.allowed.value).toBe(true);
      await f.state.execute();
      expect(f.state.operation.value).toStartWith("request:");
      const original = f.state.operation.value;
      await f.state.execute();
      expect(f.runtime.starts).toBe(1);
      f.runtime.pollResult = async () => completed;
      await f.state.resume();
      expect(f.runtime.polls).toEqual([original, original]);
      expect(f.state.operation.value).toBe("");
      expect(f.state.output.value).toContain("confirmed");
    } finally {
      f.scope.stop();
    }
  });
  it("restores an unknown request after remount and never submits another start", async () => {
    const first = fixture();
    await ready();
    await first.state.execute();
    const original = first.state.operation.value;
    first.scope.stop();
    const second = fixture(true, first.saved);
    try {
      await ready();
      expect(second.state.operation.value).toBe(original);
      await second.state.execute();
      expect(second.runtime.starts).toBe(0);
      second.runtime.pollResult = async () => completed;
      await second.state.resume();
      expect(second.runtime.polls).toEqual([original]);
      expect(second.saved.size).toBe(0);
    } finally {
      second.scope.stop();
    }
  });
  it("keeps the operation when refreshed project proof has the same identity", async () => {
    const f = fixture();
    try {
      await ready();
      await f.state.execute();
      const original = f.state.operation.value;
      f.props.context = { ...f.props.context, expires_at: "2030-02-01T00:00:00Z" };
      await ready();
      expect(f.state.operation.value).toBe(original);
      expect(f.runtime.starts).toBe(1);
    } finally {
      f.scope.stop();
    }
  });
  it("withholds a late result after the selected project changes", async () => {
    const f = fixture();
    let resolve: (value: McpOperation<string>) => void = () => {};
    f.runtime.startResult = () =>
      new Promise((complete) => {
        resolve = complete;
      });
    try {
      await ready();
      const execution = f.state.execute();
      f.props.selectedProjectId = "other";
      await ready();
      resolve(completed);
      await execution;
      expect(f.state.output.value).toBe("");
      expect(f.state.operation.value).toBe("");
      expect(f.state.busy.value).toBe(false);
    } finally {
      f.scope.stop();
    }
  });
  it("requires current project use_resources even when owner tools are present", async () => {
    const f = fixture(false);
    try {
      await ready();
      expect(f.state.allowed.value).toBe(false);
      await f.state.execute();
      expect(f.runtime.starts).toBe(0);
    } finally {
      f.scope.stop();
    }
  });
});
