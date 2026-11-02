/** Port of HTTP Bridge shared/events/bus.ts, repair b89c5f6.
 * Same-origin authenticated WebSocket, reconnect generations and scoped
 * listeners; retired SSE/mock transports and Admin API URLs are removed.
 */
import { reactive, readonly } from "vue";
import { type EventDelivery, incomingMessage, newerEventCursor, type RpcReply } from "./incoming";
import { jsonCodec } from "./protocol";
import type { BusEvent } from "./event-data";
export type { BusEvent } from "./event-data";
const history = reactive<BusEvent[]>([]);
let historySequence = 0;
type Handler = (event: BusEvent) => void;
const handlers = new Map<string, Set<Handler>>();
const state = reactive({
  status: "idle" as "idle" | "connecting" | "connected" | "reconnecting" | "error",
  sessionActive: false,
  lastRemoteEventAt: "",
  retryAttempt: 0,
  latencyMs: null as number | null,
  received: 0,
  toolCalls: 0,
  reconnects: 0,
  lastDisconnectCode: null as number | null,
  lastSequence: 0,
  deliveryGaps: 0,
  metricsEnabled: false,
  subscriptions: [] as string[],
  sources: {} as Record<
    string,
    {
      source: string;
      projectId: string | null;
      status: "connected" | "unavailable";
      lastEventAt: string;
    }
  >,
});
let socket: WebSocket | null = null,
  generation = 0,
  retry = 0,
  scope: string | null = null;
let reconnect: ReturnType<typeof setTimeout> | null = null,
  heartbeat: ReturnType<typeof setInterval> | null = null;
let pingStarted = 0,
  lastReceived = 0;
let lastCursor: string | null = null;
const pending = new Map<
  string,
  { resolve: (value: unknown) => void; reject: (error: Error) => void; cleanup: () => void }
>();
function rejectPending() {
  for (const call of pending.values()) {
    call.cleanup();
    call.reject(new Error("Соединение прервано; результат команды не подтверждён"));
  }
  pending.clear();
}
function request<T>(
  method: string,
  params: Record<string, unknown>,
  decode: (value: unknown) => T,
  signal?: AbortSignal,
): Promise<T> {
  if (socket?.readyState !== WebSocket.OPEN || pending.size >= 32 || signal?.aborted)
    return Promise.reject(new Error("Нет соединения с сервером"));
  const current = socket,
    id = crypto.randomUUID();
  return new Promise<T>((resolve, reject) => {
    const cancel = () => {
      const call = pending.get(id);
      if (call) {
        pending.delete(id);
        call.cleanup();
        reject(new Error("Ожидание ответа отменено; результат команды не подтверждён"));
      }
    };
    const timeout = setTimeout(
      cancel,
      method === "analysis.command"
        ? 30000
        : ["browser.command", "terminal.command"].includes(method)
          ? 20000
          : 8000,
    );
    const cleanup = () => {
      clearTimeout(timeout);
      signal?.removeEventListener("abort", cancel);
    };
    pending.set(id, {
      resolve: (value) => {
        try {
          resolve(decode(value));
        } catch (error) {
          reject(error instanceof Error ? error : new Error("RPC_REPLY_INVALID"));
        }
      },
      reject,
      cleanup,
    });
    signal?.addEventListener("abort", cancel, { once: true });
    try {
      current.send(jsonCodec.encode({ jsonrpc: "2.0", id, method, params }));
    } catch {
      cancel();
    }
  });
}
/** These commands deliberately consume no successful result; RPC errors still reject. */
function execute(method: string, params: Record<string, unknown> = {}, signal?: AbortSignal): Promise<void> {
  return request(method, params, () => undefined, signal);
}
function subscriptionTopics(value: unknown): { topics: string[] } {
  if (!value || typeof value !== "object" || !("topics" in value) || !Array.isArray(value.topics))
    throw new Error("SUBSCRIPTION_REPLY_INVALID");
  const topics = value.topics.map((topic: unknown) => {
    if (typeof topic !== "string") throw new Error("SUBSCRIPTION_REPLY_INVALID");
    return topic;
  });
  return { topics };
}
const seen = new Set<string>();
const topics = [
  "platform.context",
  "mcp.calls",
  "management.events",
  "browser.runtime",
  "system.metrics",
  "system.notifications",
  "access.sessions",
];
const subscribedTopics = () =>
  topics.filter((topic) => topic !== "system.metrics" || state.metricsEnabled);
async function syncSubscriptions() {
  const desired = subscribedTopics(),
    excluded = topics.filter((topic) => !desired.includes(topic));
  if (excluded.length) await execute("events.unsubscribe", { topics: excluded });
  return request("events.subscribe", { topics: desired, cursor: lastCursor }, subscriptionTopics);
}
async function setMetricsEnabled(enabled: boolean) {
  const previous = state.metricsEnabled;
  state.metricsEnabled = enabled;
  try {
    if (socket?.readyState === WebSocket.OPEN) {
      const reply = await syncSubscriptions();
      state.subscriptions = reply.topics.filter((topic) => topics.includes(topic));
    }
  } catch (error) {
    state.metricsEnabled = previous;
    throw error;
  }
}
function dispatch(event: BusEvent) {
  if (!["platform.context", "connection.state", "session.refresh"].includes(event.topic)) {
    history.unshift({ ...event, id: event.id ?? `receipt:${++historySequence}` });
    if (history.length > 200) history.pop();
  }
  for (const listener of handlers.get(event.topic) ?? []) {
    try {
      listener(event);
    } catch {
      console.warn("panel.event_listener_failed", event.topic);
    }
  }
}
function status(value: typeof state.status) {
  if (state.status === value) return;
  state.status = value;
  dispatch({
    topic: "connection.state",
    type: value,
    occurredAt: new Date().toISOString(),
    data: null,
  });
}
function close() {
  generation++;
  rejectPending();
  if (reconnect) clearTimeout(reconnect);
  reconnect = null;
  if (heartbeat) clearInterval(heartbeat);
  heartbeat = null;
  const current = socket;
  socket = null;
  current?.close();
  state.latencyMs = null;
  state.subscriptions = [];
}
function ping() {
  if (socket?.readyState !== WebSocket.OPEN) return;
  pingStarted = performance.now();
  void execute("system.ping")
    .then(() => {
      state.latencyMs = Math.round(performance.now() - pingStarted);
    })
    .catch(() => {});
}
function schedule() {
  if (!state.sessionActive) return;
  if (reconnect) clearTimeout(reconnect);
  status("reconnecting");
  state.retryAttempt = ++retry;
  reconnect = setTimeout(
    connect,
    Math.min(15000, 500 * 2 ** Math.min(retry, 5)) + Math.random() * 250,
  );
}
interface StreamPosition {
  id: string | null;
  sequence: number;
}
function settleReply(reply: RpcReply): void {
  const call = pending.get(reply.id);
  if (!call) return;
  pending.delete(reply.id);
  call.cleanup();
  if (reply.error) call.reject(reply.error);
  else call.resolve(reply.result);
}
function advanceStream(message: EventDelivery, position: StreamPosition): void {
  const stream = message.stream;
  if (!stream) return;
  if (stream.sequence !== (position.id === stream.id ? position.sequence + 1 : 1)) {
    state.deliveryGaps++;
    dispatch({
      topic: "system.notifications",
      type: "resync.required",
      occurredAt: state.lastRemoteEventAt,
      data: { reason: "delivery.gap" },
    });
  }
  position.id = stream.id;
  position.sequence = stream.sequence;
  state.lastSequence = stream.sequence;
}
function duplicateEvent(id: string | undefined): boolean {
  if (id === undefined) return false;
  if (seen.has(id)) return true;
  seen.add(id);
  if (seen.size > 2000) {
    const oldest = seen.values().next().value;
    if (oldest !== undefined) seen.delete(oldest);
  }
  return false;
}
function updateSource(message: EventDelivery): void {
  const event = message.event;
  if (
    event?.topic !== "system.notifications" ||
    !["source.connected", "source.recovered", "source.unavailable"].includes(event.type)
  )
    return;
  const data = event.data;
  if (!data || !("source" in data) || !("project_id" in data)) return;
  const projectId = data.project_id,
    key = `${data.source}:${projectId ?? ""}`;
  state.sources[key] = {
    source: data.source,
    projectId,
    status: event.type === "source.unavailable" ? "unavailable" : "connected",
    lastEventAt: state.lastRemoteEventAt,
  };
}
function deliver(message: EventDelivery): void {
  updateSource(message);
  if (message.type === "session.refresh") {
    dispatch({
      topic: "session.refresh",
      type: "refresh",
      occurredAt: state.lastRemoteEventAt,
      data: null,
    });
    return;
  }
  const event = message.event;
  if (!event) return;
  if (event.topic === "platform.context" && event.type === "snapshot") {
    retry = 0;
    state.retryAttempt = 0;
    status("connected");
  }
  if (event.topic === "mcp.calls" && event.type === "call.started") state.toolCalls++;
  dispatch({ ...event, occurredAt: event.occurredAt ?? state.lastRemoteEventAt });
}
function receive(raw: unknown, position: StreamPosition): void {
  const message = incomingMessage(jsonCodec.decode(raw));
  lastReceived = Date.now();
  state.received++;
  state.lastRemoteEventAt = new Date().toISOString();
  if (message.kind === "reply") {
    settleReply(message);
    return;
  }
  advanceStream(message, position);
  if (duplicateEvent(message.id)) return;
  if (message.cursor && newerEventCursor(message.cursor, lastCursor)) lastCursor = message.cursor;
  deliver(message);
}
function connect() {
  reconnect = null;
  if (!state.sessionActive || socket) return;
  status(retry ? "reconnecting" : "connecting");
  const current = new WebSocket(
    `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/v1/events${scope ? `?project_uuid=${encodeURIComponent(scope)}` : ""}`,
  );
  const run = ++generation;
  socket = current;
  const position: StreamPosition = { id: null, sequence: 0 };
  const isCurrent = () => socket === current && generation === run;
  current.onopen = () => {
    if (!isCurrent()) return;
    lastReceived = Date.now();
    void syncSubscriptions()
      .then((reply) => {
        if (isCurrent())
          state.subscriptions = reply.topics.filter((topic) => topics.includes(topic));
      })
      .catch(() => {
        if (isCurrent()) current.close();
      });
    ping();
    heartbeat = setInterval(() => {
      if (!isCurrent()) return;
      if (Date.now() - lastReceived > 35000) current.close();
      else ping();
    }, 15000);
  };
  current.onmessage = (event) => {
    if (!isCurrent()) return;
    try {
      receive(event.data, position);
    } catch {
      status("error");
      current.close(1008);
    }
  };
  current.onclose = (event) => {
    if (!isCurrent()) return;
    state.reconnects++;
    state.lastDisconnectCode = event.code;
    socket = null;
    rejectPending();
    if (heartbeat) clearInterval(heartbeat);
    heartbeat = null;
    if (event.code === 4401)
      dispatch({
        topic: "session.refresh",
        type: "refresh",
        occurredAt: new Date().toISOString(),
        data: null,
      });
    if (event.code === 4403) {
      status("error");
      dispatch({
        topic: "session.denied",
        type: "denied",
        occurredAt: new Date().toISOString(),
        data: null,
      });
      return;
    }
    schedule();
  };
  current.onerror = () => {
    if (isCurrent()) status("reconnecting");
  };
}
function subscribe(topic: string, handler: Handler) {
  let set = handlers.get(topic);
  if (!set) {
    set = new Set();
    handlers.set(topic, set);
  }
  set.add(handler);
  return () => {
    set?.delete(handler);
    if (!set?.size) handlers.delete(topic);
  };
}
function setSessionActive(active: boolean) {
  state.sessionActive = active;
  if (!active) {
    state.metricsEnabled = false;
    close();
    status("idle");
    state.toolCalls = 0;
    state.received = 0;
    state.lastRemoteEventAt = "";
    state.sources = {};
    lastCursor = null;
    seen.clear();
    history.splice(0);
    return;
  }
  connect();
}
function setScope(value: string | null) {
  if (value === scope) return;
  scope = value;
  lastCursor = null;
  seen.clear();
  state.sources = {};
  history.splice(0);
  close();
  connect();
}
export const eventBus = {
  setMetricsEnabled,
  state: readonly(state),
  history: readonly(history),
  subscribe,
  setSessionActive,
  setScope,
  ping,
  request,
  execute,
};
if (import.meta.hot)
  import.meta.hot.dispose(() => {
    close();
    handlers.clear();
  });
