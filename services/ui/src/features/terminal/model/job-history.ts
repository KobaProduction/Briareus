import type { TerminalJobStatus } from "./terminal-result";

export interface TerminalJobHistory {
  jobs: TerminalJobStatus[];
  total: number;
  truncated: boolean;
}

export function terminalStateLabel(state: TerminalJobStatus["state"]): string {
  const labels: Record<TerminalJobStatus["state"], string> = {
    running: "Выполняется",
    cancelling: "Останавливается",
    completed: "Завершено",
    failed: "Ошибка",
    cancelled: "Остановлено",
    timed_out: "Истекло время",
    interrupted: "Прервано",
    unknown: "Состояние не подтверждено",
  };
  return labels[state];
}
