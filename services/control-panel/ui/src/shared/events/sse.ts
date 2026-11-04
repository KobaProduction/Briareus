import { authorizationHeaders, invalidateIdentity } from "@/shared/auth/identity"

export async function streamEvents(
  path: string, signal: AbortSignal, onOpen: () => void, onMessage: (data: string) => void,
): Promise<void> {
  const response = await fetch(path, {
    headers: await authorizationHeaders({ Accept: "text/event-stream" }),
    credentials: "omit", signal,
  })
  if (response.status === 401) await invalidateIdentity()
  if (!response.ok || !response.body) throw new Error(`Event stream unavailable: ${response.status}`)
  onOpen()
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let pending = ""
  try {
    while (!signal.aborted) {
      const chunk = await reader.read()
      if (chunk.done) return
      pending += decoder.decode(chunk.value, { stream: true })
      let separator = /\r?\n\r?\n/.exec(pending)
      while (separator?.index !== undefined) {
        const frame = pending.slice(0, separator.index)
        pending = pending.slice(separator.index + separator[0].length)
        const data = frame.split(/\r?\n/).filter(line => line.startsWith("data:"))
          .map(line => line.slice(5).replace(/^ /, "")).join("\n")
        if (data) onMessage(data)
        separator = /\r?\n\r?\n/.exec(pending)
      }
    }
  } finally {
    await reader.cancel()
  }
}
