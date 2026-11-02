import { callHand, type ProjectCommandContext, type ProjectCommandSource } from "@/shared/events";
import { type McpOperation, operationValue, requireRecord } from "@/shared/lib/transport";
import type { AnalysisClient, AnalysisEngine, AnalysisInvocation } from "../model/command";
import { analysisTools, nativeAnalysisArguments } from "./tool-results";

/** This panel is a native engine result viewer; it does not orchestrate raw result fields. */
function analysisOutput(value: unknown): string {
  return JSON.stringify(requireRecord(value), null, 2);
}
function analysisOperation(value: unknown): McpOperation<string> {
  return operationValue(value, analysisOutput);
}

export function createAnalysisClient(source: ProjectCommandSource): AnalysisClient {
  function context(): ProjectCommandContext {
    const current = source();
    if (!current) throw new Error("Выберите проект");
    return current;
  }
  return {
    tools: (engine: AnalysisEngine) =>
      callHand("analysis.command", context(), "analysis_tools", { engine }, analysisTools),
    start: (input: AnalysisInvocation, requestId: string) => {
      const argumentsValue = nativeAnalysisArguments(input.argumentsText);
      if (input.projectArgument)
        argumentsValue[input.projectArgument.name] = input.projectArgument.value;
      return callHand(
        "analysis.command",
        context(),
        "analysis_start",
        {
          engine: input.engine,
          tool: input.tool,
          arguments: argumentsValue,
        },
        analysisOperation,
        requestId,
      );
    },
    poll: (operationId: string) =>
      callHand(
        "analysis.command",
        context(),
        "analysis_poll",
        { operation_id: operationId },
        analysisOperation,
      ),
    cancel: (operationId: string) =>
      callHand(
        "analysis.command",
        context(),
        "analysis_cancel",
        { operation_id: operationId },
        () => undefined,
      ),
  };
}
