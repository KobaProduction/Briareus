/** Catalogue projection: supported parameter names plus complete schema text for display. */
export interface AnalysisTool {
  name: string;
  title?: string;
  description?: string;
  inputProperties: readonly string[];
  inputSchemaText: string;
}
