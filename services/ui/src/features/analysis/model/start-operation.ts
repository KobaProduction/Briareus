import { RpcError } from "@/shared/events";

/** Only a typed, explicitly zero-dispatch preparation reply permits effect retry. */
export async function startAnalysis<T>(options: {
  start: () => Promise<T>;
  resolve: () => Promise<T>;
  current: () => boolean;
  preparing: () => void;
  wait: () => Promise<void>;
}): Promise<T> {
  while (options.current()) {
    try {
      return await options.start();
    } catch (error) {
      if (!options.current()) throw error;
      if (
        error instanceof RpcError &&
        error.message === "ANALYSIS_PREPARING" &&
        error.uncertaintyDeclared &&
        error.uncertain === false
      ) {
        options.preparing();
        await options.wait();
        continue;
      }
      if (error instanceof RpcError && error.uncertaintyDeclared && error.uncertain === false)
        throw error;
      return await options.resolve();
    }
  }
  throw new Error("Подготовка отменена: сеанс или рабочая область изменены");
}
export function preparationDelay(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new Error("Подготовка отменена"));
      return;
    }
    const abort = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      reject(new Error("Подготовка отменена"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, 1000);
    signal.addEventListener("abort", abort, { once: true });
  });
}
