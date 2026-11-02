import { watch } from "vue"
import { platformPort } from "../api/port"
import { projectContext } from "./project-context"
import { commandCoordinator, type PendingCommand } from "./command-coordinator"

export interface ReconciliationLifetime {
  signal: AbortSignal
  close: () => void
}
/** Reconciliation can never outlive the selected authority epoch or adapter.
 * Closing an unfinished original always restores its UNKNOWN retry fence. */
export function openReconciliation(entry: PendingCommand | null): ReconciliationLifetime {
  const abort = new AbortController()
  const stop = projectContext.onTransition(() => abort.abort())
  const off = watch(platformPort, () => abort.abort())
  if (entry) commandCoordinator.reconciling(entry)
  return {
    signal: abort.signal,
    close: () => {
      if (entry) commandCoordinator.unresolved(entry)
      stop()
      off()
      abort.abort()
    },
  }
}
