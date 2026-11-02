import { describe, expect, it } from "bun:test";
import type { BrowserInput } from "../src/entities/browser";
import { browserInteraction } from "../src/entities/browser";
import {
  appendBrowserInput,
  browserKey,
  browserPoint,
  browserTextInputs,
} from "../src/features/project-browser/model/browser-input";

describe("human browser input", () => {
  it("maps the scaled image back to native CSS viewport coordinates", () => {
    const surface = {
      left: 10,
      top: 20,
      width: 640,
      height: 360,
      naturalWidth: 1280,
      naturalHeight: 720,
    };
    expect(browserPoint(330, 200, surface)).toEqual({ x: 640, y: 360 });
    expect(browserPoint(9, 200, surface)).toBeNull();
    expect(browserPoint(650, 200, surface)).toBeNull();
    expect(browserPoint(10, 20, { ...surface, width: 0 })).toBeNull();
  });
  it("batches typing without losing the following Enter key", () => {
    const events: BrowserInput[] = [];
    appendBrowserInput(events, { kind: "text", text: "при" });
    appendBrowserInput(events, { kind: "text", text: "вет" });
    appendBrowserInput(events, { kind: "key", key: "Enter" });
    expect(events).toEqual([
      { kind: "text", text: "привет" },
      { kind: "key", key: "Enter" },
    ]);
  });
  it("keeps modifier keys out of text and bounds accumulated wheel motion", () => {
    const key = { key: "a", ctrlKey: false, metaKey: false, altKey: false, shiftKey: false };
    expect(browserKey(key)).toEqual({ kind: "text", text: "a" });
    expect(browserKey({ ...key, ctrlKey: true })).toEqual({ kind: "key", key: "Control+a" });
    expect(browserKey({ ...key, key: "Shift" })).toBeNull();
    expect(browserKey({ ...key, isComposing: true })).toBeNull();
    expect(browserKey({ ...key, key: "Insert", shiftKey: true })).toBeNull();
    expect(browserKey({ ...key, key: "v", ctrlKey: true })).toBeNull();
    const events: BrowserInput[] = [];
    appendBrowserInput(events, { kind: "wheel", x: 10, y: 10, delta_x: 0, delta_y: 9000 });
    appendBrowserInput(events, { kind: "wheel", x: 10, y: 10, delta_x: 0, delta_y: 9000 });
    expect(events).toEqual([{ kind: "wheel", x: 10, y: 10, delta_x: 0, delta_y: 10000 }]);
  });
  it("splits long Unicode input without losing text or splitting a surrogate pair", () => {
    const original = "a".repeat(1023) + "😀" + "текст".repeat(400);
    const events = browserTextInputs(original);
    if (!events) throw new Error("Expected accepted text");
    const text = events.map((event) => (event.kind === "text" ? event.text : ""));
    expect(text.join("")).toBe(original);
    expect(text[0]).toBe("a".repeat(1023));
    expect(text[1]?.startsWith("😀")).toBe(true);
    expect(text.every((part) => part.length <= 1024)).toBe(true);
    expect(browserTextInputs("x".repeat(65537))).toBeNull();
  });
  it("rejects an updated view for a different page", () => {
    expect(() =>
      browserInteraction(
        { snapshot: { page_id: "other", url: "https://example.com" } },
        "selected",
      ),
    ).toThrow("BROWSER_INTERACTION_INVALID");
  });
});
