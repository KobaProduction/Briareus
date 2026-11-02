/** Wire encoding is independent of RPC methods and domain DTOs.
 * JSON is the active codec; a binary codec can implement the same interface.
 */
export interface MessageCodec {
  encode(message: unknown): string | ArrayBuffer;
  decode(message: unknown): Record<string, unknown>;
}
export class RpcError extends Error {
  constructor(
    message: string,
    public uncertain: boolean,
    public uncertaintyDeclared = true,
  ) {
    super(message);
  }
}
/** Raw values are accepted only by the caller's transport decoder. */
export type ReplyDecoder<T> = (value: unknown) => T;
export const jsonCodec: MessageCodec = {
  encode: (message) => JSON.stringify(message),
  decode: (raw) => {
    if (typeof raw !== "string" || raw.length > 1048576) throw new Error("Invalid message");
    const message: unknown = JSON.parse(raw);
    if (!message || typeof message !== "object" || Array.isArray(message))
      throw new Error("Invalid envelope");
    return message as Record<string, unknown>;
  },
};
