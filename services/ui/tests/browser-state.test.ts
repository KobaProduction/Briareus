import { describe, expect, it } from "bun:test";
import {
  browserTab,
  editableBrowserElement,
  mergeBrowserInputs,
  reconcileSelection,
  transportLabel,
} from "../src/entities/browser";
import type { BrowserOperationData, BusEvent } from "../src/shared/events/event-data";
import { decodeEventData } from "../src/shared/events/event-wire";
import { mcpValue } from "../src/shared/lib/transport";
import { browserRefreshRequired } from "../src/features/project-browser/model/browser-refresh";

describe("browser controls", () => {
  it("refreshes remote changes while ignoring status probes and other projects", () => {
    const data: BrowserOperationData = {
      project_id: "project",
      operation_id: "remote",
      tool: "web_operation_start",
      status: "completed",
    };
    const event: BusEvent = {
      topic: "browser.runtime",
      type: "operation.completed",
      occurredAt: "2026-10-30T00:00:00Z",
      data,
    };
    expect(browserRefreshRequired(event, "project", new Set())).toBe(true);
    expect(browserRefreshRequired(event, "other", new Set())).toBe(false);
    expect(
      browserRefreshRequired(
        { ...event, data: { ...data, tool: "local_browser_status" } },
        "project",
        new Set(),
      ),
    ).toBe(false);
  });
  it("retains human browser activity without inventing an agent session", () => {
    const call = {
      hand: "web",
      tool: "local_browser_open",
      status: "completed",
      duration_ms: 10,
      session_uuid: null,
      node_uuid: "node",
      placement_uuid: "placement",
      transport: "gateway-mcp",
    };
    const activity = decodeEventData("management.events", "mcp.call.completed", {
      event_id: "event",
      type: "mcp.call.completed",
      occurredAt: "2026-10-29T12:00:00Z",
      actor_id: "human",
      project_id: "project",
      operation_id: "operation",
      entity_id: "placement",
      source: "access",
      ...call,
      call,
    });
    expect(activity).toMatchObject({ actor_id: "human", session_uuid: null, call });
  });
  it("clicks checkbox/radio/submit controls rather than filling them", () => {
    for (const type of ["checkbox", "radio", "submit", "button", "file"])
      expect(editableBrowserElement({ ref: "e1", tag: "input", type })).toBe(false);
  });
  it("preserves unsent text drafts while reflecting unchanged server values", () => {
    const before: [
      import("../src/entities/browser").BrowserElement,
      import("../src/entities/browser").BrowserElement,
    ] = [
      { ref: "e1", tag: "input", name: "Email", value: "old" },
      { ref: "e2", tag: "input", name: "Title", value: "server" },
    ];
    expect(
      mergeBrowserInputs(
        before,
        [
          { ...before[0], value: "new" },
          { ...before[1], value: "updated" },
        ],
        { e1: "draft", e2: "server" },
        true,
      ),
    ).toEqual({ e1: "draft", e2: "updated" });
  });
  it("never initializes or retains a password from snapshots", () =>
    expect(
      mergeBrowserInputs(
        [{ ref: "e1", tag: "input", type: "password", value: "<redacted>" }],
        [{ ref: "e1", tag: "input", type: "password", value: "<redacted>" }],
        { e1: "secret" },
        true,
      ),
    ).toEqual({}));
  it("keeps selected tab when a background tab closes", () =>
    expect(reconcileSelection([{ page_id: "selected", title: "", url: "" }], "selected")).toBe(
      "selected",
    ));
  it("selects a surviving explicit ID after closing active tab", () =>
    expect(reconcileSelection([{ page_id: "other", title: "", url: "" }], "closed")).toBe("other"));
  it("does not treat plain HTTP as encrypted", () =>
    expect(transportLabel("http://example.com")).toContain("без шифрования"));
  it("reports HTTPS without asserting certificate identity", () =>
    expect(transportLabel("https://example.com")).toBe("HTTPS · шифрованное соединение"));
  it("unwraps real MCP JSON text", () =>
    expect(
      mcpValue(
        { content: [{ type: "text", text: '{"page_id":"p","url":"https://example.com"}' }] },
        browserTab,
      ),
    ).toEqual({
      page_id: "p",
      url: "https://example.com",
      title: "",
      label: undefined,
    }));
  it("surfaces tool errors", () =>
    expect(() =>
      mcpValue({ isError: true, content: [{ type: "text", text: "tab limit" }] }, browserTab),
    ).toThrow("tab limit"));
});
