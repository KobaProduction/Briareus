/** Primitive decoding confined to the native event transport boundary. */
export function text(row: Record<string, unknown>, field: string): string {
  const value = row[field];
  if (typeof value !== "string") throw Error("Invalid event text");
  return value;
}
export function nullableText(row: Record<string, unknown>, field: string): string | null {
  return row[field] === null ? null : text(row, field);
}
export function optionalText(
  row: Record<string, unknown>,
  field: string,
): string | null | undefined {
  return row[field] === undefined ? undefined : nullableText(row, field);
}
export function numeric(row: Record<string, unknown>, field: string): number {
  const value = row[field];
  if (typeof value !== "number" || !Number.isFinite(value)) throw Error("Invalid event number");
  return value;
}
export function flag(row: Record<string, unknown>, field: string): boolean {
  const value = row[field];
  if (typeof value !== "boolean") throw Error("Invalid event flag");
  return value;
}
export function literal<T extends string | boolean>(
  row: Record<string, unknown>,
  field: string,
  expected: T,
): T {
  if (row[field] !== expected) throw Error("Invalid event discriminator");
  return expected;
}
export function list<T>(value: unknown, decode: (item: unknown) => T): T[] {
  if (!Array.isArray(value)) throw Error("Invalid event list");
  return value.map(decode);
}
