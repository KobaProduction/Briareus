import type { Ref } from "vue";
import { useEventJournal as useJournal } from "../model/use-event-journal";
import { eventJournalTransport } from "./event-journal";
export function useEventJournal(
  topics: Ref<string[]>,
  project: Ref<string | null>,
  identity: Ref<string>,
) {
  return useJournal(topics, project, identity, eventJournalTransport);
}
