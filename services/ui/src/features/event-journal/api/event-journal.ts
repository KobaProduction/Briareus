import { eventBus } from "@/shared/events";
import type { EventJournalPort } from "../model/journal-policy";
import { decodeJournalPage } from "./journal-codec";
export const eventJournalTransport: EventJournalPort = {
  get history() {
    return eventBus.history;
  },
  get status() {
    return eventBus.state.status;
  },
  async page(selection) {
    return eventBus.request("events.history", { ...selection }, (value) =>
      decodeJournalPage(value, selection.before),
    );
  },
  subscribeResync(handler) {
    return eventBus.subscribe("system.notifications", (event) => {
      if (event.type === "resync.required") handler();
    });
  },
};
