import { describe, expect, it } from "bun:test";
import {
  DEFAULT_NODE_LIMITS,
  MEBIBYTE,
  MINIMUM_MODULE_LIMITS,
  NODE_RESERVED_LIMITS,
  nodeBudgetAllowed,
  resourceAllocationAllowed,
} from "../src/entities/node";

describe("node allocation invariants", () => {
  it("keeps controller capacity separate from runnable MCP allocations", () => {
    expect(nodeBudgetAllowed(DEFAULT_NODE_LIMITS)).toBe(true);
    expect(
      nodeBudgetAllowed({ ...DEFAULT_NODE_LIMITS, cpu_millis: NODE_RESERVED_LIMITS.cpu_millis }),
    ).toBe(false);
    expect(nodeBudgetAllowed({ ...DEFAULT_NODE_LIMITS, pids: NODE_RESERVED_LIMITS.pids })).toBe(
      false,
    );
    expect(nodeBudgetAllowed({ ...DEFAULT_NODE_LIMITS, memory_bytes: 511 * MEBIBYTE })).toBe(false);
  });
  it("accepts exact allocation bounds and rejects any dimension outside the node", () => {
    expect(
      resourceAllocationAllowed(MINIMUM_MODULE_LIMITS, MINIMUM_MODULE_LIMITS, DEFAULT_NODE_LIMITS),
    ).toBe(true);
    expect(
      resourceAllocationAllowed(DEFAULT_NODE_LIMITS, MINIMUM_MODULE_LIMITS, DEFAULT_NODE_LIMITS),
    ).toBe(true);
    for (const key of ["memory_bytes", "cpu_millis", "pids"] as const) {
      expect(
        resourceAllocationAllowed(
          { ...MINIMUM_MODULE_LIMITS, [key]: MINIMUM_MODULE_LIMITS[key] - 1 },
          MINIMUM_MODULE_LIMITS,
          DEFAULT_NODE_LIMITS,
        ),
      ).toBe(false);
      expect(
        resourceAllocationAllowed(
          { ...DEFAULT_NODE_LIMITS, [key]: DEFAULT_NODE_LIMITS[key] + 1 },
          MINIMUM_MODULE_LIMITS,
          DEFAULT_NODE_LIMITS,
        ),
      ).toBe(false);
    }
  });
  it("does not accept fractional, nonfinite or negative budgets from an editor", () => {
    for (const value of [Number.NaN, Number.POSITIVE_INFINITY, -1, 1.5]) {
      expect(nodeBudgetAllowed({ ...DEFAULT_NODE_LIMITS, pids: value })).toBe(false);
      expect(
        resourceAllocationAllowed(
          { ...MINIMUM_MODULE_LIMITS, cpu_millis: value },
          MINIMUM_MODULE_LIMITS,
          DEFAULT_NODE_LIMITS,
        ),
      ).toBe(false);
    }
    expect(
      resourceAllocationAllowed(
        { ...MINIMUM_MODULE_LIMITS, memory_bytes: 64.5 * MEBIBYTE },
        MINIMUM_MODULE_LIMITS,
        DEFAULT_NODE_LIMITS,
      ),
    ).toBe(false);
  });
});
