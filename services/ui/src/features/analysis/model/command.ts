import type { McpOperation } from "@/shared/lib/transport";
import type { AnalysisTool } from "./tool";

export type AnalysisEngine = "ghidra" | "radare2";

export interface AnalysisClient {
  tools(engine: AnalysisEngine): Promise<AnalysisTool[]>;
  start(input: AnalysisInvocation, requestId: string): Promise<McpOperation<string>>;
  poll(operationId: string): Promise<McpOperation<string>>;
  cancel(operationId: string): Promise<void>;
}

export interface AnalysisInvocation {
  engine: AnalysisEngine;
  tool: string;
  argumentsText: string;
  projectArgument: { name: string; value: string } | null;
}
