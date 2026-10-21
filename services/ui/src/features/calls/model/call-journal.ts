/** HTTP Bridge repair b89c5f6 call-journal.ts, adapted to scoped signal DTOs. */
import type {BusEvent} from "@/shared/events/bus"
export type JournalEvent=BusEvent&{id:string}
export const CALL_CHUNK_SIZE=100
function newestFirst(left:JournalEvent,right:JournalEvent):number {
  return right.occurredAt.localeCompare(left.occurredAt)||right.id.localeCompare(left.id)
}
export function mergeCallJournal(current:readonly JournalEvent[],incoming:readonly JournalEvent[],limit=200):JournalEvent[]{
  const byId=new Map<string,JournalEvent>()
  for(const item of current)byId.set(item.id,item)
  for(const item of incoming)byId.set(item.id,item)
  return [...byId.values()].sort(newestFirst).slice(0,limit)
}
export function enqueueCalls(pending:readonly JournalEvent[],incoming:readonly JournalEvent[],visible:readonly JournalEvent[],limit=200):JournalEvent[]{
  const visibleIds=new Set(visible.map(item=>item.id))
  return mergeCallJournal(pending,incoming.filter(item=>!visibleIds.has(item.id)),limit)
}
