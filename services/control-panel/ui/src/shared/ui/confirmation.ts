import { shallowRef } from "vue"

type Request = { message: string; resolve: (accepted: boolean) => void }
const queue: Request[] = []
export const activeConfirmation = shallowRef<Request | null>(null)
export function requestConfirmation(message: string): Promise<boolean> {
  return new Promise((resolve) => {
    queue.push({ message, resolve })
    if (!activeConfirmation.value) activeConfirmation.value = queue.shift() ?? null
  })
}
export function settleConfirmation(accepted: boolean): void {
  const current = activeConfirmation.value
  activeConfirmation.value = queue.shift() ?? null
  current?.resolve(accepted)
}
