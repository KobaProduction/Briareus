import { describe, expect, it } from "bun:test";
import { parseAnalysisRecovery } from "../src/features/analysis/api/recovery";

const project = "11111111-1111-4111-8111-111111111111";
const request = "22222222-2222-4222-8222-222222222222";
const boot = "33333333-3333-4333-8333-333333333333";
const saved = {
  human: true,
  project_uuid: project,
  engine: "radare2",
  operation_id: "request:" + request,
};

describe("human Analysis recovery boundary", () => {
  it("accepts only a request UUID or the exact server boot/request handle", () => {
    expect(parseAnalysisRecovery(saved, project)).toEqual({
      engine: "radare2",
      operationId: "request:" + request,
    });
    expect(
      parseAnalysisRecovery({ ...saved, operation_id: boot + ":" + request }, project),
    ).toEqual({ engine: "radare2", operationId: boot + ":" + request });
  });
  it("rejects another project, agent authority and malformed operation handles", () => {
    expect(parseAnalysisRecovery(saved, boot)).toBeNull();
    for (const invalid of [
      { ...saved, human: false },
      { ...saved, agent_session_uuid: request },
      { ...saved, expected_grant_revision: 1 },
      { ...saved, operation_id: "request:arbitrary" },
      { ...saved, operation_id: request },
      { ...saved, operation_id: boot + ":" + request + ":extra" },
      { ...saved, engine: "unknown" },
    ])
      expect(parseAnalysisRecovery(invalid, project)).toBeNull();
  });
});
