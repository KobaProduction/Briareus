import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { effectScope, nextTick, ref } from "vue";
import { eventBus } from "../src/shared/events/bus";
import { useLiveQuery } from "../src/shared/lib/use-live-query";
import { oidcPagesForRole } from "../src/features/platform/model/oidc-view-routing";
import type { ContextSnapshotData } from "../src/shared/api";
import type { EventData } from "../src/shared/events/event-data";

const snapshot: ContextSnapshotData = {
  context: {
    authenticated: true,
    authority: "platform",
    rauthy: { issuer: "https://issuer.invalid", subject: "subject" },
    user: { id: "user", role: "user", enabled: true },
    teams: [],
    projects: [],
    expires_at: "2026-10-29T00:00:00Z",
  },
  identity: {
    authenticated: true,
    authority: "rauthy",
    issuer: "https://issuer.invalid",
    subject: "subject",
    client_id: "panel",
    expires_at: "2026-10-29T00:00:00Z",
    platform_membership_verified: false,
    permissions: [],
  },
};
function eventData(topic: string, type: string): EventData {
  if (topic === "platform.context") return snapshot;
  if (topic === "system.metrics")
    return {
      source: "control-panel-api",
      uptime_seconds: 1,
      cpu_user_seconds: 0,
      cpu_system_seconds: 0,
      peak_memory_kib: 1,
    };
  return { actor_id: "actor", operation_id: "operation", action: type };
}

const originalSocket = globalThis.WebSocket;
const originalLocation = Object.getOwnPropertyDescriptor(globalThis, "location");
class SocketFixture extends EventTarget implements WebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSING = 2;
  readonly CLOSED = 3;
  binaryType: BinaryType = "blob";
  bufferedAmount = 0;
  extensions = "";
  protocol = "";
  url: string;
  static current: SocketFixture;
  requests: { method: string; params: { topics?: string[] } }[] = [];
  readyState = 1;
  onopen: WebSocket["onopen"] = null;
  onmessage: WebSocket["onmessage"] = null;
  onclose: WebSocket["onclose"] = null;
  onerror: WebSocket["onerror"] = null;
  constructor(url: string | URL) {
    super();
    this.url = String(url);
    SocketFixture.current = this;
  }
  send(wire: string | ArrayBufferLike | Blob | ArrayBufferView) {
    if (typeof wire !== "string") throw new Error("Expected JSON request");
    const request: { id: string; method: string; params: { topics?: string[] } } = JSON.parse(wire);
    this.requests.push(request);
    queueMicrotask(() =>
      this.onmessage?.call(
        this,
        new MessageEvent("message", {
          data: JSON.stringify({
            jsonrpc: "2.0",
            id: request.id,
            result: { topics: request.params.topics ?? [] },
          }),
        }),
      ),
    );
  }
  close(code = 1000) {
    this.readyState = 3;
    this.onclose?.call(this, new CloseEvent("close", { code }));
  }
  open() {
    this.onopen?.call(this, new Event("open"));
  }
  deliver(sequence: number, topic: string, type: string) {
    this.onmessage?.call(
      this,
      new MessageEvent("message", {
        data: JSON.stringify({
          jsonrpc: "2.0",
          method: "events.deliver",
          params: {
            stream_id: "test-stream",
            sequence,
            topic,
            type,
            data: eventData(topic, type),
            occurredAt: "2026-10-19T00:00:00Z",
          },
        }),
      }),
    );
  }
}
const tick = async () => {
  await nextTick();
  await new Promise((resolve) => setTimeout(resolve, 0));
};
beforeEach(() => {
  globalThis.WebSocket = SocketFixture;
  Object.defineProperty(globalThis, "location", {
    configurable: true,
    value: { host: "127.0.0.1", protocol: "http:" },
  });
  eventBus.setSessionActive(true);
  SocketFixture.current.open();
  SocketFixture.current.deliver(1, "platform.context", "snapshot");
});
afterEach(() => {
  eventBus.setSessionActive(false);
  globalThis.WebSocket = originalSocket;
  if (originalLocation) Object.defineProperty(globalThis, "location", originalLocation);
  else Reflect.deleteProperty(globalThis, "location");
});
describe("live reads and recovery", () => {
  it("keeps optional system metrics off without dropping application subscriptions", async () => {
    await tick();
    const requested = () => {
      const topics = SocketFixture.current.requests
        .filter((item) => item.method === "events.subscribe")
        .at(-1)?.params.topics;
      if (!topics) throw new Error("Expected a subscription request");
      return topics;
    };
    expect(requested()).not.toContain("system.metrics");
    expect(requested()).toContain("management.events");
    await eventBus.setMetricsEnabled(true);
    expect(requested()).toContain("system.metrics");
    await eventBus.setMetricsEnabled(false);
    expect(requested()).not.toContain("system.metrics");
    expect(SocketFixture.current.requests.slice(-2).map((request) => request.method)).toEqual([
      "events.unsubscribe",
      "events.subscribe",
    ]);
    expect(requested()).toContain("platform.context");
  });
  it("keeps an event received during a read and coalesces repeated events", async () => {
    let calls = 0,
      release: () => void = () => {};
    const first = new Promise<void>((resolve) => {
      release = resolve;
    });
    const scope = effectScope();
    scope.run(() =>
      useLiveQuery(
        async () => {
          calls++;
          if (calls === 1) await first;
        },
        { enabled: () => true, topics: ["management.events"] },
      ),
    );
    SocketFixture.current.deliver(2, "management.events", "team.rename");
    SocketFixture.current.deliver(3, "management.events", "team.member.remove");
    expect(calls).toBe(1);
    release();
    await tick();
    expect(calls).toBe(2);
    scope.stop();
    SocketFixture.current.deliver(4, "management.events", "team.rename");
    await tick();
    expect(calls).toBe(2);
  });
  it("recovers a delivery gap and waits for a running mutation before reading", async () => {
    let calls = 0;
    const paused = ref(true),
      before = eventBus.state.deliveryGaps,
      scope = effectScope();
    scope.run(() =>
      useLiveQuery(
        async () => {
          calls++;
        },
        { enabled: () => true, paused: () => paused.value, topics: ["management.events"] },
      ),
    );
    SocketFixture.current.deliver(3, "system.metrics", "process.snapshot");
    expect(eventBus.state.deliveryGaps).toBe(before + 1);
    expect(calls).toBe(0);
    paused.value = false;
    await tick();
    expect(calls).toBe(1);
    scope.stop();
  });
  it("does not publish a reconnect transition on each authority snapshot", () => {
    let connected = 0;
    const stop = eventBus.subscribe("connection.state", (event) => {
      if (event.type === "connected") connected++;
    });
    SocketFixture.current.deliver(2, "platform.context", "snapshot");
    SocketFixture.current.deliver(3, "platform.context", "snapshot");
    expect(connected).toBe(0);
    stop();
  });
  it("shows the users administration section only to the verified operator role", () => {
    expect(oidcPagesForRole("user")).not.toContain("users");
    expect(oidcPagesForRole("operator")).toContain("users");
  });
});
