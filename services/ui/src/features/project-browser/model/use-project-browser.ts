import { computed, onScopeDispose, ref, watch } from "vue";
import {
  type BrowserElement,
  type BrowserInput,
  type BrowserInteraction,
  type BrowserSnapshot,
  type BrowserTab,
  editableBrowserElement,
  mergeBrowserInputs,
  reconcileSelection,
} from "@/entities/browser";
import type { VerifiedPlatformContext } from "@/entities/workspace";
import type { ProjectCommandSource } from "@/shared/events";
import type { HandEffectScope } from "@/shared/lib/hand-effect-scope";
import { useLiveQuery } from "@/shared/lib/use-live-query";
import type { BrowserPageAction, ProjectBrowserClient } from "./browser-commands";
import { appendBrowserInput } from "./browser-input";
import { browserRefreshRequired } from "./browser-refresh";

export interface ProjectBrowserWorkspaceContext {
  context: VerifiedPlatformContext;
  selectedProjectId: string | null;
}
export interface ProjectBrowserWorkspacePorts {
  resources(project: string, signal: AbortSignal): Promise<HandEffectScope[] | null>;
  client(
    source: ProjectCommandSource,
    onRequest: (id: string) => void,
    onRecovered: () => void,
  ): ProjectBrowserClient;
}
export function useProjectBrowserWorkspace(
  props: ProjectBrowserWorkspaceContext,
  ports: ProjectBrowserWorkspacePorts,
) {
  const project = computed(() =>
    props.context.projects.find((p) => p.id === props.selectedProjectId),
  );
  const identityKey = computed(() =>
    JSON.stringify([
      props.context.rauthy.issuer,
      props.context.rauthy.subject,
      props.context.user.id,
      props.selectedProjectId,
    ]),
  );
  const scopes = ref<HandEffectScope[]>([]);
  const tabs = ref<BrowserTab[]>([]),
    tabId = ref(""),
    draft = ref("https://example.com"),
    notice = ref(""),
    busy = ref(false);
  const canReopen = ref(false);
  const addressEditing = ref(false);
  const menuOpen = ref(false),
    tabsOpen = ref(false);
  const snapshot = ref<BrowserSnapshot | null>(null),
    preview = ref(""),
    zoom = ref(100),
    width = ref(1280),
    height = ref(720),
    inputValues = ref<Record<string, string>>({});
  const current = computed(() => tabs.value.find((tab) => tab.page_id === tabId.value));
  const allowed = computed(
    () => !!project.value?.permissions.includes("use_resources") && scopes.value.length > 0,
  );
  let generation = 0,
    controller = new AbortController();
  const ownRequests = new Set<string>();
  function rememberRequest(id: string) {
    if (ownRequests.size >= 512) {
      const oldest = ownRequests.values().next().value;
      if (oldest) ownRequests.delete(oldest);
    }
    ownRequests.add(id);
  }
  const browser = ports.client(
    () => {
      if (!project.value || !allowed.value) return null;
      return {
        project_uuid: project.value.id,
        signal: controller.signal,
      };
    },
    rememberRequest,
    () => live.invalidate(),
  );
  const elements = computed<BrowserElement[]>(() =>
    Array.isArray(snapshot.value?.elements) ? snapshot.value.elements : [],
  );
  function fail(error: unknown) {
    notice.value = error instanceof Error ? error.message : "Браузер недоступен";
  }
  function requireRun(run: number): void {
    if (run !== generation) throw new Error("Рабочая область изменена");
  }
  async function inventory(updateDraft = true, run = generation) {
    requireRun(run);
    const result = await browser.inventory();
    requireRun(run);
    tabs.value = result.pages;
    canReopen.value = result.canReopen;
    const next = reconcileSelection(tabs.value, tabId.value);
    if (next !== tabId.value) {
      tabId.value = next;
      if (updateDraft && !addressEditing.value)
        draft.value = tabs.value.find((tab) => tab.page_id === next)?.url ?? "https://example.com";
      snapshot.value = null;
      preview.value = "";
    }
  }
  async function load() {
    if (!project.value || busy.value) return;
    const run = generation;
    try {
      const found = await ports.resources(project.value.id, controller.signal);
      if (!found?.length) throw new Error("Браузер проекта не подключён");
      if (run !== generation) return;
      scopes.value = found;
      if (allowed.value)
        await act(async (scope) => {
          notice.value = "Браузер подготавливается…";
          await inventory(true, scope);
          if (tabId.value) await readPage(tabId.value, scope);
          notice.value = "";
        });
    } catch (error) {
      if (run === generation) fail(error);
    }
  }
  async function act(work: (run: number) => Promise<void>) {
    if (busy.value) return;
    const run = generation;
    busy.value = true;
    notice.value = "";
    try {
      await work(run);
    } catch (error) {
      if (run === generation) fail(error);
    } finally {
      if (run === generation) busy.value = false;
    }
  }
  async function readPage(id: string, run = generation) {
    requireRun(run);
    preview.value = "";
    const value = await browser.snapshot(id);
    requireRun(run);
    if (tabId.value === id) {
      inputValues.value = mergeBrowserInputs(
        elements.value,
        value.elements ?? [],
        inputValues.value,
        snapshot.value?.page_id === id && snapshot.value?.url === value.url,
      );
      snapshot.value = value;
    }
    const image = await browser.preview(id);
    requireRun(run);
    if (tabId.value === id) {
      snapshot.value = value;
      preview.value = "";
      preview.value = image;
    }
  }
  function selectTab(id: string) {
    if (busy.value || !allowed.value || !tabs.value.some((tab) => tab.page_id === id)) return;
    clearBrowserInput();
    tabsOpen.value = false;
    tabId.value = id;
    draft.value = current.value?.url ?? "";
    snapshot.value = null;
    preview.value = "";
    void act((run) => readPage(id, run));
  }
  function navigate(newTab = false) {
    if (busy.value || !allowed.value) return;
    clearBrowserInput();
    const address = newTab ? "about:blank" : draft.value.trim();
    try {
      const parsed = new URL(address);
      if (!newTab && !["http:", "https:"].includes(parsed.protocol)) throw 0;
    } catch {
      notice.value = "Введите полный HTTP или HTTPS адрес";
      return;
    }
    const selected = newTab ? "" : tabId.value;
    void act(async (run) => {
      const result = await browser.open(address, selected);
      requireRun(run);
      await inventory(false, run);
      tabId.value = result.page_id;
      if (newTab || draft.value.trim() === address)
        draft.value = result.url === "about:blank" ? "" : result.url;
      await readPage(result.page_id, run);
    });
  }
  function closeTab(id: string) {
    if (busy.value || !allowed.value) return;
    clearBrowserInput();
    const wasActive = tabId.value === id;
    void act(async (run) => {
      await browser.close(id);
      requireRun(run);
      await inventory(true, run);
      if (wasActive && tabId.value) await readPage(tabId.value, run);
    });
  }
  function browserMenu(action: "restore" | "settings" | "extensions") {
    if (!allowed.value || busy.value || (action === "restore" && !canReopen.value)) return;
    clearBrowserInput();
    menuOpen.value = false;
    void act(async (run) => {
      const result =
        action === "restore" ? await browser.restore() : await browser.settings(action);
      requireRun(run);
      await inventory(true, run);
      tabId.value = result.page_id;
      draft.value = result.url;
      await readPage(result.page_id, run);
    });
  }
  let inputTimer: ReturnType<typeof setTimeout> | undefined;
  let pendingInputs: BrowserInput[] = [];
  let inputTarget = "";
  let inputEpoch = 0;
  let inputFlight = -1;
  function clearBrowserInput() {
    inputEpoch++;
    if (inputTimer !== undefined) clearTimeout(inputTimer);
    inputTimer = undefined;
    pendingInputs = [];
    inputTarget = "";
  }
  function flushBrowserInput() {
    if (inputTimer !== undefined) clearTimeout(inputTimer);
    inputTimer = undefined;
    if (busy.value) return;
    const id = tabId.value;
    const target = id;
    if (!allowed.value || target !== inputTarget || !pendingInputs.length) {
      clearBrowserInput();
      return;
    }
    const events = pendingInputs.splice(0, 4);
    const epoch = inputEpoch;
    const run = generation;
    inputFlight = epoch;
    void act(async () => {
      try {
        const result = await browser.input(id, events);
        if (epoch !== inputEpoch || run !== generation || tabId.value !== id) return;
        applyBrowserInteraction(result);
      } catch (error) {
        if (epoch === inputEpoch) clearBrowserInput();
        throw error;
      }
    }).finally(() => {
      if (inputFlight === epoch) inputFlight = -1;
      if (epoch === inputEpoch) flushBrowserInput();
    });
  }
  function applyBrowserInteraction(result: BrowserInteraction) {
    tabs.value = result.inventory.pages;
    canReopen.value = result.inventory.canReopen;
    inputValues.value = mergeBrowserInputs(
      elements.value,
      result.snapshot.elements,
      inputValues.value,
      snapshot.value?.page_id === result.snapshot.page_id &&
        snapshot.value?.url === result.snapshot.url,
    );
    snapshot.value = result.snapshot;
    preview.value = result.preview;
    if (!addressEditing.value) draft.value = result.snapshot.url;
  }
  function acceptsBrowserInput(): boolean {
    return (
      !(busy.value && inputFlight !== inputEpoch) &&
      allowed.value &&
      !!tabId.value &&
      !!preview.value
    );
  }
  function queueBrowserInputs(inputs: BrowserInput[], immediate = false) {
    if (!acceptsBrowserInput()) return;
    const target = tabId.value;
    if (inputTarget !== target) clearBrowserInput();
    const next: BrowserInput[] = pendingInputs.map((event) => ({ ...event }));
    for (const input of inputs) appendBrowserInput(next, input);
    if (next.length > 64) {
      notice.value = "Дождитесь обработки предыдущего ввода";
      return;
    }
    inputTarget = target;
    pendingInputs = next;
    if (immediate || pendingInputs.length >= 4) flushBrowserInput();
    else {
      if (inputTimer !== undefined) clearTimeout(inputTimer);
      inputTimer = setTimeout(flushBrowserInput, 150);
    }
  }
  function pageAction(tool: BrowserPageAction) {
    if (busy.value || !allowed.value || !tabId.value) return;
    clearBrowserInput();
    const id = tabId.value;
    void act(async (run) => {
      await browser.navigate(tool, id);
      requireRun(run);
      await inventory(true, run);
      if (tabId.value === id) {
        draft.value = current.value?.url ?? draft.value;
        await readPage(id, run);
      }
    });
  }
  function resize() {
    if (busy.value || !allowed.value || !tabId.value) return;
    clearBrowserInput();
    if (
      !Number.isInteger(width.value) ||
      !Number.isInteger(height.value) ||
      width.value < 320 ||
      height.value < 240 ||
      width.value > 7680 ||
      height.value > 4320
    ) {
      notice.value = "Размер страницы: ширина 320–7680, высота 240–4320 пикселей";
      return;
    }
    const id = tabId.value;
    void act(async (run) => {
      const result = await browser.viewport(id, width.value, height.value);
      requireRun(run);
      width.value = result.width ?? width.value;
      height.value = result.height ?? height.value;
      await readPage(id, run);
    });
  }
  function interact(element: BrowserElement) {
    if (busy.value || !allowed.value || !tabId.value) return;
    clearBrowserInput();
    const id = tabId.value;
    void act(async (run) => {
      const editable = editableBrowserElement(element);
      try {
        if (editable) await browser.fill(id, element.ref, inputValues.value[element.ref] ?? "");
        else await browser.click(id, element.ref);
      } finally {
        if (run === generation && (element.type ?? "").toLowerCase() === "password")
          delete inputValues.value[element.ref];
      }
      requireRun(run);
      await inventory(true, run);
      await readPage(id, run);
    });
  }
  watch(
    identityKey,
    () => {
      generation++;
      controller.abort();
      controller = new AbortController();
      busy.value = false;
      scopes.value = [];
      ownRequests.clear();
      clearBrowserInput();
      tabs.value = [];
      canReopen.value = false;
      tabId.value = "";
      snapshot.value = null;
      preview.value = "";
      draft.value = "https://example.com";
      addressEditing.value = false;
      inputValues.value = {};
      notice.value = "";
    },
    { immediate: true, flush: "sync" },
  );
  const live = useLiveQuery(load, {
    enabled: () => !!project.value,
    paused: () => busy.value,
    topics: ["management.events", "browser.runtime"],
    accept: (event) => browserRefreshRequired(event, props.selectedProjectId, ownRequests),
  });
  watch(identityKey, () => live.invalidate());
  onScopeDispose(() => {
    clearBrowserInput();
    generation++;
    controller.abort();
  });

  return {
    project,
    tabs,
    tabId,
    draft,
    addressEditing,
    notice,
    busy,
    canReopen,
    menuOpen,
    tabsOpen,
    snapshot,
    preview,
    zoom,
    width,
    height,
    inputValues,
    current,
    allowed,
    elements,
    selectTab,
    navigate,
    closeTab,
    browserMenu,
    queueBrowserInputs,
    pageAction,
    resize,
    interact,
  };
}
