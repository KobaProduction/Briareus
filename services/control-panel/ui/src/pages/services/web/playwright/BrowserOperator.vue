<script setup lang="ts">
import { requestConfirmation } from "@/shared/ui/confirmation"
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { Select } from "ant-design-vue"
import {
  PopoverContent,
  PopoverPortal,
  PopoverRoot,
  PopoverTrigger,
} from "reka-ui"
import Switch from "@/shared/ui/Switch.vue"
import AppDialog from "@/shared/ui/AppDialog.vue"
import Button from "@/shared/ui/Button.vue"
import InternalBrowserSettings from "./settings/InternalBrowserSettings.vue"
import {
  ArrowLeft,
  ChevronDown,
  Circle,
  Code2,
  Settings,
  Ellipsis,
  ExternalLink,
  List,
  LockKeyhole,
  Monitor,
  Plus,
  Puzzle,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-vue-next"
import { useI18n } from "vue-i18n"

import {
  controlPanelApi,
  type BrowserTabPolicy,
} from "@/shared/api/control-panel"
import { authenticatedSocket, invalidateIdentity } from "@/shared/auth/identity"
import { eventBus } from "@/shared/events/bus"
import { pageActivity } from "@/shared/lib/page-activity"
import { notifications } from "@/shared/notifications/bus"
import { frontendTelemetry } from "@/shared/telemetry/client"

import type { BrowserOperatorState, BrowserOperatorMessage, BrowserOperatorCommand, BrowserClipboardMessage } from "@/shared/api/browser-contracts"

const { t } = useI18n()
const state = ref<BrowserOperatorState>({})
const pendingSelection = ref<string | null>(null)
const framePageId = ref("")
const allTabsOpen = ref(false)
const settingsOpen = ref(false)
const preferencesOpen = ref(false)
const runtimeAction = ref<"" | "restart" | "stop" | "reset">("")
let recoveringUntil = 0
const keyboardTarget = ref<HTMLTextAreaElement | null>(null)
const pendingCopies = new Map<string, { page: string; cut: boolean; timer: number }>()
const status = ref<"connecting" | "live" | "disconnected" | "error">(
  "connecting",
)
const message = ref("")
const addressDraft = ref("")
const addressFocused = ref(false)
const viewportPreset = ref("1280x720")
const themePreset = ref<"system" | "light" | "dark">("dark")
const screen = ref<HTMLImageElement | null>(null)
const dims = ref({ w: 1280, h: 720 })
let ws: WebSocket | null = null
let connecting = false
let wsGeneration = 0
let reconnect = 0
let activityUnsubscribe: undefined | (() => void)
let disconnectNotified = false
let refresh = 0
let lastMove = 0
let lastSelected = ""

const pages = computed(() => state.value.pages ?? [])
const selectedId = computed(
  () => pendingSelection.value ?? state.value.selected_page_id ?? "",
)
const selectedPage = computed(
  () => pages.value.find((page) => page.page_id === selectedId.value) ?? null,
)
const live = computed(() => status.value === "live")
function capabilityEnabled(name: string): boolean {
  const capabilities = state.value.capabilities
  if (Array.isArray(capabilities)) return capabilities.includes(name)
  if (capabilities && typeof capabilities === "object")
    return capabilities[name] === true
  return false
}
const canSetViewport = computed(() => capabilityEnabled("set_viewport"))
const canSetTheme = computed(() => capabilityEnabled("set_theme"))
const viewportOptions = computed(() => [
  { label: `${t("browser.mobile")} · 360 × 800`, value: "360x800" },
  { label: `${t("browser.mobile")} · 390 × 844`, value: "390x844" },
  { label: `${t("browser.mobile")} · 412 × 915`, value: "412x915" },
  { label: `${t("browser.tablet")} · 768 × 1024`, value: "768x1024" },
  { label: `${t("browser.tablet")} · 1024 × 768`, value: "1024x768" },
  { label: "1280 × 720", value: "1280x720" },
  { label: "1440 × 900", value: "1440x900" },
  { label: "1920 × 1080", value: "1920x1080" },
  { label: "2560 × 1440", value: "2560x1440" },
])

function send(payload: BrowserOperatorCommand): boolean {
  if (ws?.readyState !== WebSocket.OPEN) return false
  ws.send(JSON.stringify(payload))
  return true
}

function syncAddress(): void {
  const page = selectedPage.value
  if (!page) return
  if (!addressFocused.value || page.page_id !== lastSelected)
    addressDraft.value = page.url ?? ""
  lastSelected = page.page_id
}

function notifyConnectionFailure(description = message.value): void {
  if (!pageActivity.isActive() || disconnectNotified || Date.now() < recoveringUntil) return
  disconnectNotified = true
  notifications.error(String(t("notifications.websocketError")), description)
}

function scheduleBrowserReconnect(delay: number): void {
  clearTimeout(reconnect)
  reconnect = 0
  if (!pageActivity.isActive()) return
  reconnect = window.setTimeout(() => {
    reconnect = 0
    void connect()
  }, delay)
}

async function connect(): Promise<void> {
  if (
    connecting ||
    (ws &&
      (ws.readyState === WebSocket.OPEN ||
        ws.readyState === WebSocket.CONNECTING))
  )
    return
  if (runtimeAction.value === "restart" || runtimeAction.value === "stop") return
  connecting = true
  status.value = "connecting"
  message.value = String(t("browser.connecting"))
  try {
    const scheme = location.protocol === "https:" ? "wss:" : "ws:"
    const generation = ++wsGeneration
    const current = await authenticatedSocket(
      `${scheme}//${location.host}/api/browser/operator/ws`,
    )
    if (generation !== wsGeneration) {
      current.close()
      return
    }
    ws = current
    const isCurrent = () => ws === current && generation === wsGeneration

    current.onopen = () => {
      if (!isCurrent()) return
      frontendTelemetry.websocket("connected", "browser.operator", "websocket")
    }
    current.onclose = (event) => {
      if (!isCurrent()) return
      pendingSelection.value = null
      clearPendingCopies()
      ws = null
      status.value = "disconnected"
      frontendTelemetry.websocket(
        "disconnected",
        "browser.operator",
        "websocket",
      )
      if (event.code === 4401) {
        message.value = String(t("browser.authorizationExpired"))
        void invalidateIdentity()
        return
      }
      if (event.code === 4403) {
        status.value = "error"
        message.value = String(t("browser.connectionFailed"))
        notifyConnectionFailure()
        return
      }
      message.value = String(t("browser.reconnecting"))
      notifyConnectionFailure(message.value)
      scheduleBrowserReconnect(1000)
    }
    current.onerror = () => {
      if (!isCurrent()) return
      status.value = "error"
      message.value = String(t("browser.connectionFailed"))
      if (Date.now() >= recoveringUntil) frontendTelemetry.websocket("error", "browser.operator")
      // onclose owns the user notification so error+close cannot double-notify.
    }
    current.onmessage = (event) => {
      if (!isCurrent()) return
      const payload = JSON.parse(event.data) as BrowserOperatorMessage
      if (payload.type === "state") {
        state.value = payload
        runtimeAction.value = ""
        recoveringUntil = 0
        if (payload.selected_page_id === pendingSelection.value || (Array.isArray(payload.pages) && payload.pages.length === 0))
          pendingSelection.value = null
        if (payload.viewport?.width && payload.viewport?.height) {
          dims.value = { w: payload.viewport.width, h: payload.viewport.height }
          const preset = `${payload.viewport.width}x${payload.viewport.height}`
          if (viewportOptions.value.some((option) => option.value === preset))
            viewportPreset.value = preset
        }
        if (
          payload.color_scheme === "system" ||
          payload.color_scheme === "light" ||
          payload.color_scheme === "dark"
        )
          themePreset.value = payload.color_scheme
        status.value = "live"
        message.value = ""
        disconnectNotified = false
        eventBus.publishMock("browser.runtime", "state", {
          pages: Array.isArray(payload.pages) ? payload.pages.length : 0,
          selected_page_id: payload.selected_page_id ?? null,
        })
        syncAddress()
      } else if (payload.type === "clipboard") {
        void receiveClipboard(payload)
      } else if (payload.type === "frame") {
        const target =
          payload.page_id === selectedId.value ? screen.value : null
        if (target) {
          target.src = `data:image/jpeg;base64,${payload.data}`
          framePageId.value = payload.page_id
        }
        const dimension = dims
        if (payload.metadata && payload.page_id === selectedId.value)
          dimension.value = {
            w: payload.metadata.deviceWidth ?? dimension.value.w,
            h: payload.metadata.deviceHeight ?? dimension.value.h,
          }
      } else if (payload.type === "error") {
        if (typeof payload.request_id === "string") {
          discardCopy(payload.request_id)
          clipboardFailure()
          return
        }
        pendingSelection.value = null
        syncAddress()
        status.value = current.readyState === WebSocket.OPEN ? "live" : "error"
        const limit =
          typeof payload.max_tabs === "number" &&
          Number.isFinite(payload.max_tabs)
            ? payload.max_tabs
            : (state.value.tab_policy?.max_tabs ?? 20)
        message.value =
          payload.code === "browser_tab_limit"
            ? t("browser.tabLimitReached", { limit })
            : (payload.message ?? String(t("browser.connectionFailed")))
        // Operation failures do not invalidate an otherwise live transport.
        notifications.error(
          String(t("notifications.websocketError")),
          message.value,
        )
      }
    }
  } catch (caught) {
    status.value = "error"
    message.value =
      caught instanceof Error
        ? caught.message
        : String(t("browser.connectionFailed"))
    frontendTelemetry.error("browser.connect", caught)
    notifyConnectionFailure()
    scheduleBrowserReconnect(3000)
  } finally {
    connecting = false
  }
}

function navigate(): void {
  const value = addressDraft.value.trim()
  if (!value) return
  send({ type: "navigate", url: value })
  addressFocused.value = false
}
function clearFrame(): void {
  framePageId.value = ""
  screen.value?.removeAttribute("src")
}
function selectPage(pageId: string): void {
  allTabsOpen.value = false
  if (pageId === selectedId.value) return
  if (!send({ type: "select_page", page_id: pageId })) return
  pendingSelection.value = pageId
  clearFrame()
  syncAddress()
}
function closePage(pageId: string = selectedId.value): void {
  if (pageId) send({ type: "close_page", page_id: pageId })
}
function closeAllPages(): void {
  if (!send({ type: "close_all_pages" })) return
  pendingSelection.value = null
  clearFrame()
}
function newPage(): void {
  send({ type: "new_page" })
}
async function developer(value?: boolean): Promise<void> {
  settingsOpen.value = false
  const allow = value ?? state.value.developer_access_enabled !== true
  if (allow && !await requestConfirmation(String(t("browser.developerConfirm")))) return
  send({ type: "set_developer_access", allowed: allow })
}
async function setViewport(value: string): Promise<void> {
  const previous = viewportPreset.value
  viewportPreset.value = value
  if (!canSetViewport.value || !selectedId.value) return
  const [width, height] = value.split("x").map(Number)
  if (!width || !height) return
  try {
    await controlPanelApi.setBrowserViewport(selectedId.value, width, height)
    dims.value = { w: width, h: height }
    frontendTelemetry.event("browser.viewport_change", {
      page_id: selectedId.value,
      width,
      height,
    })
  } catch (caught) {
    viewportPreset.value = previous
    notifications.error(String(t("browser.connectionFailed")), caught instanceof Error ? caught.message : "")
    frontendTelemetry.error("browser.viewport_change_failed", caught, {
      page_id: selectedId.value,
      width,
      height,
    })
  }
}
async function setTheme(value: string): Promise<void> {
  if (!canSetTheme.value || !["system", "light", "dark"].includes(value)) return
  const scheme = value as "system" | "light" | "dark"
  const previous = themePreset.value
  themePreset.value = scheme
  try {
    const result = await controlPanelApi.setBrowserTheme(scheme)
    themePreset.value = result.color_scheme ?? scheme
    frontendTelemetry.event("browser.theme_change", { color_scheme: scheme })
  } catch (caught) {
    themePreset.value = previous
    frontendTelemetry.error("browser.theme_change_failed", caught, {
      color_scheme: scheme,
    })
  }
}
function openSpecialPage(
  url: "chrome://settings/" | "chrome://extensions/",
): void {
  settingsOpen.value = false
  const prefix = url.slice(0, -1)
  const existing = pages.value.find(
    (page) =>
      page.url === prefix ||
      page.url?.startsWith(`${prefix}/`) ||
      page.url?.startsWith(`${prefix}?`),
  )
  if (existing) selectPage(existing.page_id)
  else send({ type: "new_page", url })
}
function selectPopupContainer(trigger: HTMLElement): HTMLElement {
  return trigger.parentElement ?? document.body
}
function suspendBrowserConnection(): void {
  recoveringUntil = Date.now() + 20_000
  clearTimeout(reconnect)
  clearPendingCopies()
  const current = ws
  ws = null
  wsGeneration += 1
  current?.close()
  clearFrame()
  pendingSelection.value = null
  status.value = "connecting"
  message.value = t("browser.runtimeChanging")
}
async function runRuntimeAction(action: "restart" | "stop"): Promise<void> {
  if (runtimeAction.value) return
  runtimeAction.value = action
  suspendBrowserConnection()
  try {
    if (action === "restart") await controlPanelApi.browserRestart()
    else await controlPanelApi.browserHardStop()
    notifications.success(String(t(action === "restart" ? "browser.restarted" : "browser.stopped")))
  } catch (caught) {
    recoveringUntil = 0
    notifications.error(String(t("browser.connectionFailed")), caught instanceof Error ? caught.message : "")
  } finally {
    runtimeAction.value = ""
    void connect()
  }
}
function acceptTabPolicy(policy: BrowserTabPolicy): void {
  state.value = { ...state.value, tab_policy: policy }
}

async function cleanApp(): Promise<void> {
  settingsOpen.value = false
  if (await requestConfirmation(String(t("browser.cleanAppConfirm")))) send({ type: "clean_app" })
}
async function cleanBrowser(): Promise<void> {
  settingsOpen.value = false
  if (runtimeAction.value || !await requestConfirmation(String(t("browser.cleanBrowserConfirm")))) return
  if (send({ type: "clean_browser" })) {
    recoveringUntil = Date.now() + 20_000
    runtimeAction.value = "reset"
    clearPendingCopies()
    clearFrame()
  }
}
function pointer(
  img: HTMLImageElement | null,
  page: string,
  d: { w: number; h: number },
  event: MouseEvent,
  type: string,
  button = "none",
  click_count = 0,
): void {
  if (!img?.src || !page) return
  if (type === "mousePressed") keyboardTarget.value?.focus({ preventScroll: true })
  const rect = img.getBoundingClientRect()
  send({
    type: "mouse",
    page_id: page,
    event: type,
    x: ((event.clientX - rect.left) * d.w) / rect.width,
    y: ((event.clientY - rect.top) * d.h) / rect.height,
    button,
    click_count,
  })
}
function wheel(
  img: HTMLImageElement | null,
  page: string,
  d: { w: number; h: number },
  event: WheelEvent,
): void {
  if (!img?.src || !page) return
  const rect = img.getBoundingClientRect()
  send({
    type: "mouse",
    page_id: page,
    event: "mouseWheel",
    x: ((event.clientX - rect.left) * d.w) / rect.width,
    y: ((event.clientY - rect.top) * d.h) / rect.height,
    delta_x: event.deltaX,
    delta_y: event.deltaY,
  })
  event.preventDefault()
}
function key(page: string, event: KeyboardEvent): void {
  if (!page || runtimeAction.value || event.isComposing) return
  if (["Control", "Meta", "Alt", "Shift"].includes(event.key)) return
  const shortcut = (event.ctrlKey || event.metaKey) && !event.altKey
  const letter = event.key.toLowerCase()
  if (shortcut && letter === "v") return // Native paste delivers the host clipboard.
  if (shortcut && (letter === "c" || letter === "x")) {
    event.preventDefault()
    copySelection(letter === "x")
    return
  }
  if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === "t") {
    send({ type: "reopen_closed_page" })
    event.preventDefault()
    return
  }
  if (event.ctrlKey || event.altKey || event.metaKey || event.key.length > 1) {
    const parts: string[] = []
    if (event.ctrlKey) parts.push("Control")
    if (event.altKey) parts.push("Alt")
    if (event.metaKey) parts.push("Meta")
    if (event.shiftKey && event.key.length > 1) parts.push("Shift")
    parts.push(event.key)
    send({ type: "key", page_id: page, key: parts.join("+") })
  } else send({ type: "text", page_id: page, text: event.key })
  event.preventDefault()
}
function clipboardFailure(): void {
  notifications.error(String(t("browser.clipboardFailed")), String(t("browser.clipboardHint")))
}
function discardCopy(id: string): void {
  const pending = pendingCopies.get(id)
  if (pending) clearTimeout(pending.timer)
  pendingCopies.delete(id)
}
function clearPendingCopies(): void {
  for (const id of pendingCopies.keys()) discardCopy(id)
}
function copySelection(cut: boolean): void {
  const page = selectedId.value
  if (!page || !live.value) return
  const id = crypto.randomUUID()
  const timer = window.setTimeout(() => { discardCopy(id); clipboardFailure() }, 10_000)
  pendingCopies.set(id, { page, cut, timer })
  if (!send({ type: "clipboard_read", page_id: page, request_id: id })) discardCopy(id)
}
async function receiveClipboard(payload: BrowserClipboardMessage): Promise<void> {
  const pending = pendingCopies.get(payload.request_id)
  discardCopy(payload.request_id)
  if (!pending || pending.page !== payload.page_id || selectedId.value !== pending.page || !payload.text) return
  try {
    await navigator.clipboard.writeText(payload.text)
    if (pending.cut && selectedId.value === pending.page) send({ type: "key", page_id: pending.page, key: "Control+x" })
  } catch { clipboardFailure() }
}
function paste(event: ClipboardEvent): void {
  const text = event.clipboardData?.getData("text/plain") ?? ""
  if (text.length > 100_000) { clipboardFailure(); return }
  if (text && selectedId.value && !runtimeAction.value) send({ type: "text", page_id: selectedId.value, text })
  if (keyboardTarget.value) keyboardTarget.value.value = ""
}
function inputText(event: Event): void {
  const target = event.target as HTMLTextAreaElement
  if (target.value && selectedId.value) send({ type: "text", page_id: selectedId.value, text: target.value })
  target.value = ""
}
function now(): number {
  return window.performance.now()
}
function mouseButton(event: MouseEvent): string {
  return event.button === 2 ? "right" : event.button === 1 ? "middle" : "left"
}

function reconnectWithToken(): void {
  if (connecting) return
  const current = ws
  ws = null
  wsGeneration += 1
  current?.close()
  void connect()
}

onMounted(() => {
  window.addEventListener("briareus:token-renewed", reconnectWithToken)
  activityUnsubscribe = pageActivity.subscribe((active) => {
    if (!active || ws) return
    clearTimeout(reconnect)
    reconnect = 0
    void connect()
  })
  void connect()
  refresh = window.setInterval(() => {
    if (pageActivity.isActive() && !pendingSelection.value)
      send({ type: "refresh_state" })
  }, 1500)
})
onBeforeUnmount(() => {
  window.removeEventListener("briareus:token-renewed", reconnectWithToken)
  clearPendingCopies()
  activityUnsubscribe?.()
  clearInterval(refresh)
  clearTimeout(reconnect)
  const current = ws
  ws = null
  wsGeneration += 1
  current?.close()
})
</script>

<template>
  <div class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3">
    <div class="flex flex-wrap items-center gap-x-6 gap-y-3">
      <label class="flex items-center gap-3 text-sm"><ShieldCheck class="size-4 text-muted-foreground" />{{ t("browser.agents") }}<Switch :model-value="state.agent_access_enabled !== false" :disabled="!live || Boolean(runtimeAction)" @update:model-value="send({ type: 'set_agent_access', allowed: $event })" /></label>
      <label class="flex items-center gap-3 text-sm"><Code2 class="size-4 text-muted-foreground" />{{ t("browser.agentDeveloper") }}<Switch :model-value="state.developer_access_enabled === true" :disabled="!live || Boolean(runtimeAction)" @update:model-value="developer" /></label>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button variant="outline" size="sm" :disabled="Boolean(runtimeAction)" @click="runRuntimeAction('restart')"><RefreshCw class="mr-2 size-4" :class="runtimeAction === 'restart' && 'animate-spin'" />{{ t("services.restartBrowser") }}</Button>
      <Button variant="outline" size="sm" @click="preferencesOpen = true"><Settings class="mr-2 size-4" />{{ t("browser.playwrightSettings") }}</Button>
    </div>
  </div>
  <AppDialog :open="preferencesOpen" :title="t('browser.playwrightSettings')" :close-label="t('common.close')" width="680px" @close="preferencesOpen = false">
    <p class="mb-5 text-sm text-muted-foreground">{{ t("browser.settingsHint") }}</p>
    <div class="space-y-3">
            <div class="flex items-center justify-between gap-2 px-2 py-1.5">
              <span class="inline-flex items-center gap-2"
                ><Monitor class="size-4" />{{ t("browser.viewport") }}</span
              ><Select
                :value="viewportPreset"
                :options="viewportOptions"
                class="w-52 max-w-[55vw]"
                size="small"
                :disabled="!live || !canSetViewport"
                :get-popup-container="selectPopupContainer"
                @change="setViewport(String($event))"
              />
            </div>
            <div class="flex items-center justify-between gap-2 px-2 py-1.5">
              <span class="inline-flex items-center gap-2"
                ><Circle class="size-4" />{{ t("browser.browserTheme") }}</span
              ><Select
                :value="themePreset"
                :options="[
                  { label: t('common.system'), value: 'system' },
                  { label: t('common.dark'), value: 'dark' },
                  { label: t('common.light'), value: 'light' },
                ]"
                class="w-52 max-w-[55vw]"
                size="small"
                :disabled="!live || !canSetTheme"
                :get-popup-container="selectPopupContainer"
                @change="setTheme(String($event))"
              />
            </div>

      <InternalBrowserSettings :policy="state.tab_policy" :runtime-busy="Boolean(runtimeAction)" @runtime-action="runRuntimeAction" @policy-applied="acceptTabPolicy" />
    </div>
    <template #footer><Button variant="outline" @click="preferencesOpen = false">{{ t("common.close") }}</Button></template>
  </AppDialog>
  <div
    class="overflow-hidden rounded-xl border border-border/70 bg-card shadow-sm"
  >
    <div
      class="flex h-10 items-end gap-1 border-b border-border/70 bg-muted/60 px-2 pt-1"
    >
      <PopoverRoot v-model:open="allTabsOpen">
        <PopoverTrigger as-child>
          <button
            type="button"
            class="mb-1 grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-accent"
            :title="t('browser.allTabs')"
            :aria-label="t('browser.allTabs')"
          >
            <List class="size-4" />
          </button>
        </PopoverTrigger>
        <PopoverPortal>
          <PopoverContent
            align="start"
            side="bottom"
            :side-offset="6"
            class="z-50 max-h-[70vh] w-96 max-w-[90vw] overflow-y-auto rounded-xl border border-border bg-popover p-2 text-popover-foreground shadow-xl outline-none"
          >
            <div
              v-for="page in pages"
              :key="page.page_id"
              class="flex items-center gap-1 rounded-md"
              :class="page.page_id === selectedId && 'bg-accent'"
            >
              <button
                type="button"
                class="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-2 text-left text-xs hover:bg-accent"
                :disabled="!live"
                @click="selectPage(page.page_id)"
              >
                <Circle
                  class="size-2.5 shrink-0"
                  :class="
                    page.page_id === selectedId
                      ? 'fill-emerald-500 text-emerald-500'
                      : 'fill-muted-foreground text-muted-foreground'
                  "
                />
                <span class="min-w-0 flex-1 truncate">{{
                  page.title || page.label || t("browser.untitled")
                }}</span>
                <span
                  class="max-w-28 truncate text-[10px] text-muted-foreground"
                  >{{ page.url }}</span
                >
              </button>
              <button
                type="button"
                class="grid size-7 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                :disabled="!live"
                :title="t('browser.close')"
                :aria-label="
                  t('browser.closeTabNamed', {
                    name: page.title || page.label || t('browser.untitled'),
                  })
                "
                @click.stop="closePage(page.page_id)"
              >
                <X class="size-3.5" />
              </button>
            </div>
            <p
              v-if="!pages.length"
              class="px-2 py-3 text-xs text-muted-foreground"
            >
              {{ t("browser.noTabs") }}
            </p>
            <button
              type="button"
              class="browser-menu-row mt-2 border-t border-border disabled:opacity-50"
              :disabled="!live || !pages.length"
              @click="closeAllPages"
            >
              <X class="size-4" />{{ t("browser.closeAllTabs") }}
            </button>
          </PopoverContent>
        </PopoverPortal>
      </PopoverRoot>

      <div class="flex min-w-0 flex-1 gap-1 overflow-x-auto">
        <button
          v-for="page in pages"
          :key="page.page_id"
          class="group flex h-8 min-w-32 max-w-52 flex-1 items-center gap-2 rounded-t-lg border border-transparent px-2 text-left text-[11px]"
          :class="
            page.page_id === selectedId
              ? 'border-border/70 border-b-card bg-card text-foreground'
              : 'text-muted-foreground hover:bg-accent/70 hover:text-foreground'
          "
          @click="selectPage(page.page_id)"
        >
          <span class="min-w-0 flex-1 truncate">{{
            page.title || page.label || t("browser.untitled")
          }}</span>
          <span
            class="grid size-5 shrink-0 place-items-center rounded hover:bg-muted"
            @click.stop="closePage(page.page_id)"
            ><X class="size-3"
          /></span>
        </button>
      </div>
      <button
        class="mb-1 grid size-7 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
        :title="String(t('browser.newTab'))"
        @click="newPage"
      >
        <Plus class="size-4" />
      </button>
    </div>

    <div
      class="flex h-11 items-center gap-1.5 border-b border-border/70 bg-card px-2"
    >
      <button
        class="browser-tool"
        :disabled="!live"
        :title="String(t('browser.back'))"
        @click="send({ type: 'back' })"
      >
        <ArrowLeft class="size-4" />
      </button>
      <button
        class="browser-tool"
        :disabled="!live"
        :title="String(t('browser.reload'))"
        @click="send({ type: 'reload' })"
      >
        <RefreshCw class="size-4" />
      </button>
      <form
        class="mx-1 flex min-w-0 flex-1 items-center rounded-full border border-border/70 bg-muted/55 px-3 focus-within:border-ring"
        @submit.prevent="navigate"
      >
        <LockKeyhole class="mr-2 size-3.5 shrink-0 text-muted-foreground" />
        <input
          v-model="addressDraft"
          class="h-8 min-w-0 flex-1 bg-transparent text-xs outline-none"
          :placeholder="t('browser.addressPlaceholder')"
          @focus="addressFocused = true"
          @blur="addressFocused = false"
        />
        <button
          type="submit"
          class="grid size-6 place-items-center rounded-full text-muted-foreground hover:bg-accent hover:text-foreground"
          :title="String(t('browser.go'))"
        >
          <ExternalLink class="size-3.5" />
        </button>
      </form>
      <button
        class="browser-tool"
        :disabled="!live"
        :title="String(t('browser.extensions'))"
        @click="openSpecialPage('chrome://extensions/')"
      >
        <Puzzle class="size-4" />
      </button>
      <span class="mx-1 h-5 w-px bg-border" />
      <span
        class="inline-flex items-center gap-1 text-[10px]"
        :class="
          live
            ? 'text-emerald-500'
            : status === 'error'
              ? 'text-destructive'
              : 'text-amber-500'
        "
        :title="message || status"
        ><Circle class="size-2.5 fill-current"
      /></span>
      <PopoverRoot v-model:open="settingsOpen">
        <PopoverTrigger as-child>
          <button
            type="button"
            class="browser-tool"
            :title="t('browser.more')"
            :aria-label="t('browser.more')"
          >
            <Ellipsis class="size-4" />
          </button>
        </PopoverTrigger>
        <PopoverPortal>
          <PopoverContent
            align="end"
            side="bottom"
            :side-offset="8"
            class="z-50 max-h-[80vh] w-80 max-w-[90vw] overflow-y-auto rounded-xl border border-border bg-popover p-2 text-xs text-popover-foreground shadow-xl outline-none"
          >
            <button
              class="browser-menu-row"
              @click="send({ type: 'reopen_closed_page' })"
            >
              <RotateCcw class="size-4" />{{ t("browser.reopen") }}
            </button>
            <button
              class="browser-menu-row"
              @click="openSpecialPage('chrome://extensions/')"
            >
              <Puzzle class="size-4" />{{ t("browser.extensions") }}
            </button>
            <button
              class="browser-menu-row"
              @click="openSpecialPage('chrome://settings/')"
            >
              <Settings class="size-4" />{{ t("browser.browserSettings") }}
            </button>
            <div class="my-1 border-t border-border" />
            <button class="browser-menu-row" @click="cleanApp">
              <Trash2 class="size-4" />{{ t("browser.cleanApp") }}
            </button>
            <button
              class="browser-menu-row text-destructive"
              @click="cleanBrowser"
            >
              <Trash2 class="size-4" />{{ t("browser.cleanBrowser") }}
            </button>

          </PopoverContent>
        </PopoverPortal>
      </PopoverRoot>
    </div>

    <div class="grid">
      <div class="browser-screen relative min-h-[560px] border-0">
        <textarea ref="keyboardTarget" class="sr-only" :aria-label="t('browser.keyboardInput')" autocomplete="off" autocapitalize="off" :spellcheck="false" @keydown="key(selectedId, $event)" @paste.prevent="paste" @copy.prevent="copySelection(false)" @cut.prevent="copySelection(true)" @input="inputText" />
        <div
          v-if="!selectedId || framePageId !== selectedId"
          class="pointer-events-none absolute inset-0 grid place-items-center p-6 text-sm text-muted-foreground"
        >
          {{ t(selectedId ? "browser.loadingTab" : "browser.noTabs") }}
        </div>
        <img
          ref="screen"
          tabindex="0"
          v-show="selectedId && framePageId === selectedId"
          :alt="t('browser.liveBrowser')"
          @mousedown.prevent="
            pointer(
              screen,
              selectedId,
              dims,
              $event,
              'mousePressed',
              mouseButton($event),
              1,
            )
          "
          @mouseup="
            pointer(
              screen,
              selectedId,
              dims,
              $event,
              'mouseReleased',
              mouseButton($event),
              1,
            )
          "
          @mousemove="
            (event) => {
              const n = now()
              if (n - lastMove > 33) {
                lastMove = n
                pointer(screen, selectedId, dims, event, 'mouseMoved')
              }
            }
          "
          @wheel="wheel(screen, selectedId, dims, $event)"
          @keydown="key(selectedId, $event)"
          @paste.prevent="paste"
          @copy.prevent="copySelection(false)"
          @cut.prevent="copySelection(true)"
          @contextmenu.prevent
        />
        <span
          class="pointer-events-none absolute bottom-2 right-2 rounded bg-black/65 px-2 py-1 text-[10px] text-white/70"
          >{{ dims.w }}×{{ dims.h }}</span
        >
      </div>
    </div>
  </div>
</template>
