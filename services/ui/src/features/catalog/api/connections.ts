import { readBoundedJsonResponse } from "@/shared/lib/transport"
import { CONTROL_PANEL_API_V1 } from "@/shared/config"
import type { ConnectionCommand } from "../model/connection-contracts"

export type ConnectionReply<T> = { kind: "ready"; value: T } | { kind: "failed"; message: string }
const messages: Partial<Record<number, string>> = {
  401: "Войдите в панель заново", 403: "Управление подключениями доступно оператору проекта",
  404: "Подключение не найдено", 409: "Запись уже существует. Обновите список",
  422: "Проверьте параметры сервиса и доступность учётной записи",
}
/** One same-origin request only. A failed outbound mutation is never replayed. */
export async function requestConnection<T>(command: ConnectionCommand, project: string, signal: AbortSignal,
  parse: (value: unknown) => T | null): Promise<ConnectionReply<T>> {
  try {
    const response = await fetch(`${CONTROL_PANEL_API_V1}/connections`, {
      method: "POST", credentials: "same-origin", cache: "no-store", mode: "same-origin",
      redirect: "error", referrerPolicy: "no-referrer", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...command, project_uuid: project }), signal,
    })
    const data: unknown = await readBoundedJsonResponse(response, signal, 131072, true)
    if (!response.ok) return { kind: "failed", message: messages[response.status] ?? "Сервис подключений недоступен. Обновите список перед повтором" }
    const value = parse(data)
    return value ? { kind: "ready", value } : { kind: "failed", message: "Сервис вернул некорректный ответ" }
  } catch {
    return { kind: "failed", message: "Ответ не получен. Обновите список, чтобы уточнить результат" }
  }
}
