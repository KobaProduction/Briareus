/** Common, pure validation of the owner's bounded public MCP projections. */
const OWNER_OPERATIONS = new Set([
  "files.read",
  "files.write",
  "project.metadata.read",
  "terminal.execute",
  "web.access",
  "analysis.import",
  "agents.manage",
  "integrations.use",
  "variables.use",
  "integrations.manage",
  "variables.manage",
]);
export function exactProjectionFields(
  data: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[] = [],
): boolean {
  const fields = [...required, ...optional.filter((field) => Object.hasOwn(data, field))];
  return (
    Object.keys(data).length === fields.length &&
    fields.every((field) => Object.hasOwn(data, field))
  );
}
export function ownerInstant(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /(?:Z|[+-][0-2][0-9]:[0-5][0-9])$/.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}
export interface OwnerDescription {
  label: string | null;
  created_at: string | null;
}
export function ownerDescription(row: Record<string, unknown>): OwnerDescription | null {
  const label = row.label ?? null,
    created = row.created_at ?? null;
  if (
    label !== null &&
    (typeof label !== "string" ||
      label.length < 1 ||
      [...label].length > 128 ||
      [...label].some(
        (character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127,
      ))
  )
    return null;
  if (created !== null && !ownerInstant(created)) return null;
  return { label, created_at: created };
}
export function ownerOperations(value: unknown): string[] | null {
  if (
    !Array.isArray(value) ||
    value.length < 1 ||
    value.length > 32 ||
    new Set(value).size !== value.length
  )
    return null;
  const operations: string[] = [];
  for (const operation of value) {
    if (typeof operation !== "string" || !OWNER_OPERATIONS.has(operation)) return null;
    operations.push(operation);
  }
  return operations;
}
export function positiveRevision(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1;
}
