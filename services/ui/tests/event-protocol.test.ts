import { describe, expect, it } from "bun:test";
import { incomingMessage, newerEventCursor } from "../src/shared/events/incoming";

describe("event and RPC wire boundary", () => {
  it("preserves explicitly declared dispatch uncertainty without manufacturing it", () => {
    for (const uncertain of [false, true, undefined]) {
      const message = incomingMessage({
        jsonrpc: "2.0",
        id: "call",
        error: { message: "PREPARING", data: { uncertain } },
      });
      if (message.kind !== "reply") throw new Error("Expected RPC reply");
      expect(message.error?.uncertain).toBe(uncertain === true);
      expect(message.error?.uncertaintyDeclared).toBe(typeof uncertain === "boolean");
    }
  });
  it("decodes the full delivery frame and rejects a malformed notification envelope", () => {
    const event = {
      stream_id: "stream",
      sequence: 3,
      event_id: "event",
      cursor: "10-2",
      topic: "management.events",
      type: "team.rename",
      data: { actor_id: "actor", operation_id: "operation", action: "team.rename" },
    };
    expect(incomingMessage({ jsonrpc: "2.0", method: "events.deliver", params: event })).toEqual({
      kind: "delivery",
      id: "event",
      cursor: "10-2",
      stream: { id: "stream", sequence: 3 },
      type: "team.rename",
      event: {
        id: "event",
        topic: "management.events",
        type: "team.rename",
        occurredAt: null,
        data: { actor_id: "actor", operation_id: "operation", action: "team.rename" },
      },
    });
    expect(() => incomingMessage({ jsonrpc: "2.0", method: "events.deliver", params: [] })).toThrow(
      "MCP_RESULT_INVALID",
    );
  });
  it("compares sequence cursors numerically and never regresses after replay", () => {
    expect(newerEventCursor("10-2", "9-99")).toBe(true);
    expect(newerEventCursor("10-2", "10-2")).toBe(false);
    expect(newerEventCursor("10-1", "10-2")).toBe(false);
    expect(newerEventCursor("0010-03", "10-2")).toBe(true);
  });
});
