import { recordValue, requireRecord } from "../lib/transport";
import { RpcError } from "./protocol";
import type { BusEvent } from "./event-data";
import { decodeEventData } from "./event-wire";

export interface RpcReply {
  kind: "reply";
  id: string;
  result: unknown;
  error: RpcError | null;
}
export interface EventDelivery {
  kind: "delivery";
  id: string | undefined;
  cursor: string | null;
  stream: { id: string; sequence: number } | null;
  type: string | null;
  event: (Omit<BusEvent, "occurredAt"> & { occurredAt: string | null }) | null;
}
function rpcError(value: unknown): RpcError | null {
  if (!value) return null;
  const error = recordValue(value),
    data = recordValue(error?.data);
  return new RpcError(
    String(error?.message ?? "UNAVAILABLE"),
    data?.uncertain === true,
    typeof data?.uncertain === "boolean",
  );
}
export function incomingMessage(wire: Record<string, unknown>): RpcReply | EventDelivery {
  const message =
    wire.jsonrpc === "2.0" && wire.method === "events.deliver" ? requireRecord(wire.params) : wire;
  if (message.jsonrpc === "2.0" && typeof message.id === "string") {
    return {
      kind: "reply",
      id: message.id,
      result: message.result,
      error: rpcError(message.error),
    };
  }
  const stream =
    typeof message.stream_id === "string" &&
    typeof message.sequence === "number" &&
    Number.isSafeInteger(message.sequence)
      ? { id: message.stream_id, sequence: message.sequence }
      : null;
  const topic = typeof message.topic === "string" ? message.topic : null;
  const eventType = typeof message.type === "string" ? message.type : null;
  const id = typeof message.event_id === "string" ? message.event_id : undefined;
  return {
    kind: "delivery",
    id,
    cursor:
      typeof message.cursor === "string" && /^\d+-\d+$/.test(message.cursor)
        ? message.cursor
        : null,
    stream,
    type: eventType,
    event:
      topic !== null && eventType !== null
        ? {
            id,
            topic,
            type: eventType,
            occurredAt: typeof message.occurredAt === "string" ? message.occurredAt : null,
            data: decodeEventData(topic, eventType, message.data),
          }
        : null,
  };
}
function cursorNumbers(cursor: string): readonly [bigint, bigint] {
  const [time, index] = cursor.split("-");
  if (time === undefined || index === undefined) throw new Error("Invalid event cursor");
  return [BigInt(time), BigInt(index)];
}
/** Accepted stream cursors advance monotonically across reconnects. */
export function newerEventCursor(cursor: string, previous: string | null): boolean {
  if (!previous) return true;
  const next = cursorNumbers(cursor),
    before = cursorNumbers(previous);
  return next[0] > before[0] || (next[0] === before[0] && next[1] > before[1]);
}
