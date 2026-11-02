import { describe, expect, it } from "bun:test";
import { effectScope, nextTick, reactive } from "vue";
import type {
  BrowserInput,
  BrowserInteraction,
  BrowserInventory,
  BrowserSnapshot,
} from "../src/entities/browser";
import type { VerifiedPlatformContext } from "../src/entities/workspace";
import type { ProjectBrowserClient } from "../src/features/project-browser/model/browser-commands";
import { useProjectBrowserWorkspace } from "../src/features/project-browser/model/use-project-browser";

class Browser implements ProjectBrowserClient {
  inputs: BrowserInput[][] = [];
  previews: string[] = [];
  opens = 0;
  constructor(private readonly project: () => string) {}
  page() {
    return {
      page_id: "page-" + this.project(),
      title: "Page",
      url: "https://" + this.project() + ".example",
    };
  }
  image() {
    return "data:image/png;base64,fixture";
  }
  content(): BrowserSnapshot {
    return { ...this.page(), text: "", text_truncated: false, elements: [] };
  }
  view(): BrowserInteraction {
    return {
      inventory: { pages: [this.page()], canReopen: false },
      snapshot: this.content(),
      preview: this.image(),
    };
  }
  snapshotResult: ((id: string) => Promise<BrowserSnapshot>) | null = null;
  inputResult: ((events: BrowserInput[]) => Promise<BrowserInteraction>) | null = null;
  async running() {
    return true;
  }
  async inventory(): Promise<BrowserInventory> {
    return { pages: [this.page()], canReopen: false };
  }
  async snapshot(id: string) {
    return this.snapshotResult ? this.snapshotResult(id) : this.content();
  }
  async preview(id: string) {
    this.previews.push(id);
    return this.image();
  }
  async open() {
    this.opens++;
    return this.page();
  }
  async restore() {
    return this.page();
  }
  async settings() {
    return this.page();
  }
  async input(_id: string, events: BrowserInput[]) {
    this.inputs.push(events);
    return this.inputResult ? this.inputResult(events) : this.view();
  }
  async close() {}
  async navigate() {}
  async viewport() {
    return { width: 1280, height: 720 };
  }
  async click() {}
  async fill() {}
}
function fixture() {
  const context: VerifiedPlatformContext = {
    authenticated: true,
    authority: "platform",
    rauthy: { issuer: "https://issuer.invalid", subject: "member" },
    user: { id: "member", role: "user", enabled: true },
    teams: [],
    projects: ["project", "other"].map((id) => ({
      id,
      owner: { kind: "user", id: "member" },
      permissions: ["use_resources"],
    })),
    expires_at: "2030-01-01T00:00:00Z",
  };
  const props = reactive({ context, selectedProjectId: "project" });
  const browser = new Browser(() => props.selectedProjectId),
    scope = effectScope();
  const state = scope.run(() =>
    useProjectBrowserWorkspace(props, {
      resources: async () => [
        {
          hand: "web",
          tool: "local_browser_pages",
          action: "web.access",
          resource: { kind: "browser_session", id: props.selectedProjectId },
        },
      ],
      client: () => browser,
    }),
  );
  if (!state) throw new Error("Expected Browser workspace");
  return { browser, props, scope, state };
}
async function settled() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await nextTick();
}

describe("project Browser workspace lifecycle", () => {
  it("keeps queued text when a new tab is refused during another input request", async () => {
    const f = fixture();
    let finish: (value: BrowserInteraction) => void = () => {};
    try {
      await settled();
      f.browser.inputResult = () =>
        new Promise((resolve) => {
          finish = resolve;
        });
      f.state.queueBrowserInputs([{ kind: "text", text: "first" }], true);
      f.state.queueBrowserInputs([{ kind: "text", text: "second" }]);
      f.state.navigate(true);
      expect(f.browser.opens).toBe(0);
      f.browser.inputResult = null;
      finish(f.browser.view());
      await settled();
      expect(f.browser.inputs).toEqual([
        [{ kind: "text", text: "first" }],
        [{ kind: "text", text: "second" }],
      ]);
    } finally {
      f.scope.stop();
    }
  });
  it("does not overwrite the address being edited with a delayed page interaction", async () => {
    const f = fixture();
    let finish: (value: BrowserInteraction) => void = () => {};
    try {
      await settled();
      f.browser.inputResult = () =>
        new Promise((resolve) => {
          finish = resolve;
        });
      f.state.queueBrowserInputs([{ kind: "text", text: "search" }], true);
      f.state.addressEditing.value = true;
      f.state.draft.value = "https://new.example";
      finish(f.browser.view());
      await settled();
      expect(f.state.draft.value).toBe("https://new.example");
    } finally {
      f.scope.stop();
    }
  });
  it("rejects a late snapshot and clears previous project drafts on scope change", async () => {
    const f = fixture();
    let finish: (value: BrowserSnapshot) => void = () => {};
    f.browser.snapshotResult = () =>
      new Promise((resolve) => {
        finish = resolve;
      });
    try {
      await settled();
      const old = f.browser.content();
      f.state.inputValues.value = { private: "previous-project-content" };
      f.props.selectedProjectId = "other";
      f.browser.snapshotResult = null;
      finish(old);
      await settled();
      expect(f.browser.previews).toEqual(["page-other"]);
      expect(f.state.tabId.value).toBe("page-other");
      expect(f.state.inputValues.value).toEqual({});
      expect(f.state.draft.value).toBe("https://other.example");
    } finally {
      f.scope.stop();
    }
  });
});
