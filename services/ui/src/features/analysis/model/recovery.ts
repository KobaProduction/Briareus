import type { AnalysisEngine } from "./command";

export interface AnalysisRecovery {
  engine: AnalysisEngine;
  operationId: string;
}
export interface AnalysisRecoveryPort {
  restore(key: string, project: string | null): AnalysisRecovery | null;
  save(key: string, project: string, recovery: AnalysisRecovery): void;
  forget(key: string): void;
}
