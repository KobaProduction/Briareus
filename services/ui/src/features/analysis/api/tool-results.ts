import { recordValue, requireRecord } from "@/shared/lib/transport";
import type { AnalysisTool } from "../model/tool";

function analysisTool(value: unknown): AnalysisTool {
  const row = requireRecord(value);
  if (typeof row.name !== "string") throw new Error("ANALYSIS_TOOL_INVALID");
  const schema = recordValue(row.inputSchema) ?? {};
  const properties = recordValue(schema.properties) ?? undefined;
  return {
    name: row.name,
    title: typeof row.title === "string" ? row.title : undefined,
    description: typeof row.description === "string" ? row.description : undefined,
    inputProperties: Object.keys(properties ?? {}),
    inputSchemaText: JSON.stringify({ ...schema, properties }, null, 2),
  };
}
export function analysisTools(value: unknown): AnalysisTool[] {
  const row = recordValue(value);
  const items = Array.isArray(value) ? value : (row?.tools ?? row?.items);
  if (!Array.isArray(items)) throw new Error("ANALYSIS_TOOLS_INVALID");
  return items.map(analysisTool);
}
/** The JSON editor is transport input, never an application payload contract. */
export function nativeAnalysisArguments(text: string): Record<string, unknown> {
  const value: unknown = JSON.parse(text);
  return requireRecord(value);
}
export function updateAnalysisArgument(text: string, name: string, value: string): string {
  return JSON.stringify({ ...nativeAnalysisArguments(text), [name]: value }, null, 2);
}
