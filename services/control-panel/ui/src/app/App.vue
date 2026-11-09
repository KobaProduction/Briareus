<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  onBeforeUnmount,
  onMounted,
  ref,
} from "vue"
import { Moon, PanelLeftClose, PanelLeftOpen, Sun } from "lucide-vue-next"
import { useI18n } from "vue-i18n"
import {
  controlPanelApi,
  type ControlPanelBootstrap,
  type SessionState,
} from "@/shared/api/control-panel"
import {
  identityAccount,
  initializeIdentity,
  signIn,
  type IdentityAccount,
} from "@/shared/auth/identity"
import { setLocale } from "@/shared/i18n"
import { runtimeConfig } from "@/shared/config/runtime"
import { panelFailure, type PanelFailure } from "@/shared/auth/errors"
import { accountStore } from "@/features/accounts/model/account-store"
import { callStore } from "@/pages/calls/model/call-store"
import { settingsStore } from "@/shared/settings/store"
import { useUiPreferences } from "@/shared/lib/preferences"
import { frontendTelemetry } from "@/shared/telemetry/client"
import { eventBus, type BusEvent } from "@/shared/events/bus"
import {
  notifications,
  type NotificationLevel,
} from "@/shared/notifications/bus"
import Button from "@/shared/ui/Button.vue"
import AuthLocaleSwitch from "@/shared/ui/AuthLocaleSwitch.vue"
import RealtimeStatus from "@/shared/ui/RealtimeStatus.vue"
import SidebarNav from "@/shared/ui/SidebarNav.vue"
import ConfirmationHost from "@/shared/ui/ConfirmationHost.vue"
import LoadingSkeleton from "@/shared/ui/LoadingSkeleton.vue"
import ToastHost from "@/shared/notifications/ToastHost.vue"
import { useServiceCatalog } from "@/shared/services/store"
import { serviceForRoute } from "@/shared/services/catalog"

const brandLogoUrl = `${import.meta.env.BASE_URL}briareus.svg`

const DashboardPage = defineAsyncComponent(
  () => import("@/pages/dashboard/DashboardPage.vue"),
)
const CallsPage = defineAsyncComponent(
  () => import("@/pages/calls/CallsPage.vue"),
)
const FilesPage = defineAsyncComponent(
  () => import("@/pages/services/server/ServerFilesPage.vue"),
)
const TerminalPage = defineAsyncComponent(
  () => import("@/pages/services/server/ServerTerminalPage.vue"),
)
const SettingsPage = defineAsyncComponent(
  () => import("@/pages/settings/SettingsPage.vue"),
)
const ServicesPage = defineAsyncComponent(
  () => import("@/pages/services/ServicesPage.vue"),
)
const ConnectionsPage = defineAsyncComponent(
  () => import("@/pages/connections/ConnectionsPage.vue"),
)
const providerPages: Record<string, ReturnType<typeof defineAsyncComponent>> = {
  github: defineAsyncComponent(
    () => import("@/pages/services/svc/github/GitHubPage.vue"),
  ),
  gitlab: defineAsyncComponent(
    () => import("@/pages/services/svc/gitlab/GitLabPage.vue"),
  ),
  signoz: defineAsyncComponent(
    () => import("@/pages/services/observability/signoz/SigNozPage.vue"),
  ),
  coolify: defineAsyncComponent(
    () => import("@/pages/services/infrastructure/coolify/CoolifyPage.vue"),
  ),
  playwright: defineAsyncComponent(
    () => import("@/pages/services/web/playwright/PlaywrightPage.vue"),
  ),
  analysis: defineAsyncComponent(
    () => import("@/pages/services/analysis/analysis/AnalysisPage.vue"),
  ),
  radare2: defineAsyncComponent(
    () => import("@/pages/services/analysis/radare2/Radare2Page.vue"),
  ),
  "analysis-g": defineAsyncComponent(
    () => import("@/pages/services/analysis/analysis/AnalysisPage.vue"),
  ),
  serena: defineAsyncComponent(
    () => import("@/pages/services/server/serena/SerenaPage.vue"),
  ),
  ghidra: defineAsyncComponent(
    () => import("@/pages/services/analysis/ghidra/GhidraPage.vue"),
  ),
}

const { t, locale } = useI18n()
const session = ref<SessionState | null>(null),
  bootstrap = ref<ControlPanelBootstrap | null>(null),
  loading = ref(true),
  gatewayUnavailable = ref(false),
  failure = ref<PanelFailure | null>(null)
const account = ref<IdentityAccount | null>(null)
const accountName = computed(
  () => account.value?.displayName.trim() || t("app.account"),
)
const error = computed(() => (failure.value ? t(failure.value.messageKey) : ""))
const activePath = ref(location.hash.slice(1) || "dashboard")
const catalog = useServiceCatalog()
let discoveryTimer: ReturnType<typeof setInterval> | null = null
let unsubscribeNotifications: undefined | (() => void)
const { theme, sidebarCollapsed } = useUiPreferences()
const selectedServiceId = computed(() => serviceForRoute(activePath.value))
const selectedService = computed(() =>
  selectedServiceId.value
    ? catalog.service(selectedServiceId.value)
    : undefined,
)
const serviceAvailable = computed(
  () => !selectedServiceId.value || selectedService.value?.connected === true,
)
const current = computed(() => {
  const root = activePath.value.split("/")[0]
  if (selectedServiceId.value) {
    const id = selectedServiceId.value
    const providerPage = Object.hasOwn(providerPages, id) ? providerPages[id] : undefined
    const component =
      id === "server"
        ? activePath.value.endsWith("terminal")
          ? TerminalPage
          : FilesPage
        : (providerPage ?? ServicesPage)
    return {
      id: activePath.value,
      label: selectedService.value?.name ?? id,
      component,
      props: providerPage || id === "server" ? {} : { serviceId: id },
    }
  }
  const pages = {
    dashboard: { label: t("nav.dashboard"), component: DashboardPage },
    calls: { label: t("nav.calls"), component: CallsPage },
    settings: { label: t("nav.settings"), component: SettingsPage },
    connections: { label: t("services.connections"), component: ConnectionsPage },
    services: { label: t("services.connections"), component: ConnectionsPage },
  }
  const page = Object.hasOwn(pages, root) ? pages[root as keyof typeof pages] : pages.dashboard
  return { id: root, label: page.label, component: page.component, props: {} }
})
function rememberSession(value: SessionState): void {
  session.value = value
  eventBus.setSessionActive(value.authenticated)
  accountStore.setSessionActive(value.authenticated)
  callStore.setSessionActive(value.authenticated)
  settingsStore.setSessionActive(value.authenticated)
}
function syncIdentity(): void {
  account.value = identityAccount()
  if (account.value?.locale) setLocale(account.value.locale)
}
function expireAuth(): void {
  syncIdentity()
  rememberSession({ authenticated: false, username: null, subject: null })
  bootstrap.value = null
  catalog.clear()
  gatewayUnavailable.value = false
}
function changeAccount(): void {
  expireAuth()
  void load()
}
function readHash(): void {
  activePath.value = location.hash.slice(1) || "dashboard"
}
async function refreshServices(): Promise<void> {
  if (session.value?.authenticated && !document.hidden) await catalog.refresh()
}
async function load(): Promise<void> {
  loading.value = true
  gatewayUnavailable.value = false
  failure.value = null
  try {
    if (!runtimeConfig.preview && !(await initializeIdentity())) {
      expireAuth()
      return
    }
    syncIdentity()
    const next = await controlPanelApi.session()
    rememberSession(next)
    readHash()
    bootstrap.value = next.authenticated
      ? await controlPanelApi.bootstrap()
      : null
    if (bootstrap.value) {
      catalog.accept(bootstrap.value)
      document.title = `Briareus V1 · ${bootstrap.value.node.id}`
    }
  } catch (e) {
    expireAuth()
    failure.value = panelFailure(e)
    gatewayUnavailable.value = failure.value.retry
  } finally {
    loading.value = false
  }
}
async function login(selectAccount = false): Promise<void> {
  try {
    failure.value = null
    await signIn(locale.value === "ru" ? "ru" : "en", selectAccount)
  } catch (caught) {
    failure.value = panelFailure(caught)
  }
}
function toggleTheme() {
  theme.value = theme.value === "dark" ? "light" : "dark"
}
function systemNotification(event: BusEvent) {
  const data = (event.data ?? {}) as Record<string, unknown>
  const level = (
    ["info", "success", "warning", "error"].includes(String(data.level))
      ? String(data.level)
      : "info"
  ) as NotificationLevel
  notifications.push({
    level,
    title: String(data.title ?? "System notification"),
    description:
      typeof data.description === "string" ? data.description : undefined,
  })
}
onMounted(() => {
  accountStore.start()
  callStore.start()
  settingsStore.start()
  readHash()
  window.addEventListener("hashchange", readHash)
  window.addEventListener("briareus:auth-expired", expireAuth)
  window.addEventListener("briareus:account-changed", changeAccount)
  unsubscribeNotifications = eventBus.subscribe(
    "system.notifications",
    systemNotification,
  )
  discoveryTimer = setInterval(() => {
    void refreshServices()
  }, 15000)
  load()
})
onBeforeUnmount(() => {
  if (discoveryTimer) clearInterval(discoveryTimer)
  accountStore.stop()
  callStore.stop()
  settingsStore.stop()
  window.removeEventListener("hashchange", readHash)
  window.removeEventListener("briareus:auth-expired", expireAuth)
  window.removeEventListener("briareus:account-changed", changeAccount)
  unsubscribeNotifications?.()
})
</script>
<template>
  <ToastHost />
  <ConfirmationHost />
  <div
    v-if="loading"
    class="grid min-h-screen place-items-center bg-background text-sm text-muted-foreground"
  >
    <LoadingSkeleton class="w-full max-w-5xl" :rows="8" :columns="3" />
  </div>
  <div
    v-else-if="gatewayUnavailable && !session?.authenticated"
    class="grid min-h-screen place-items-center bg-background p-6"
  >
    <section
      class="w-full max-w-md rounded-xl border border-border bg-card p-6 text-center shadow-sm"
    >
      <img :src="brandLogoUrl" alt="" width="48" height="48" class="mx-auto mb-3 size-12" />
      <h1 class="text-lg font-semibold">Briareus</h1>
      <p class="mt-2 text-sm text-muted-foreground">{{ error }}</p>
      <p v-if="failure?.requestId" class="mt-2 text-xs text-muted-foreground">
        {{ t("authErrors.requestId", { id: failure.requestId }) }}
      </p>
      <Button class="mt-5" @click="load">{{ t("common.retry") }}</Button
      ><Button
        v-if="account"
        variant="ghost"
        class="mt-2"
        @click="login(true)"
        >{{ t("app.switchAccount") }}</Button
      >
      <div><AuthLocaleSwitch v-if="!account && error" /></div>
    </section>
  </div>
  <div
    v-else-if="!session?.authenticated"
    class="grid min-h-screen place-items-center bg-muted/30 p-6"
  >
    <section
      class="w-full max-w-sm rounded-xl border border-border bg-card p-6 shadow-sm"
    >
      <div class="flex items-center gap-3">
        <img :src="brandLogoUrl" alt="" width="48" height="48" class="size-12 shrink-0" />
        <h1 class="text-xl font-semibold">{{ t("app.title") }}</h1>
      </div>
      <p class="mt-1 text-sm text-muted-foreground">{{ t("app.console") }}</p>
      <p v-if="account?.displayName" class="mt-6 text-sm font-medium">
        {{ account.displayName }}
      </p>
      <p v-else class="mt-6 text-sm text-muted-foreground">
        {{ t("app.identitySignIn") }}
      </p>
      <p v-if="error" role="alert" class="mt-4 text-sm text-destructive">
        {{ error }}
      </p>
      <p v-if="failure?.requestId" class="mt-2 text-xs text-muted-foreground">
        {{ t("authErrors.requestId", { id: failure.requestId }) }}
      </p>
      <div v-if="account" class="mt-5 grid gap-2">
        <Button @click="login(true)">{{ t("app.switchAccount") }}</Button>
      </div>
      <Button v-else class="mt-4 w-full" @click="login()">{{
        t("app.signInWithIdentity")
      }}</Button
      ><AuthLocaleSwitch v-if="!account && error" />
    </section>
  </div>
  <div
    v-else-if="bootstrap"
    class="grid min-h-screen bg-background text-foreground"
    :class="sidebarCollapsed ? 'grid-cols-[68px_1fr]' : 'grid-cols-[240px_1fr]'"
  >
    <aside class="sticky top-0 flex h-screen min-h-0 flex-col border-r border-border bg-sidebar p-3">
      <div class="mb-5 flex min-h-10 items-center justify-between" :class="sidebarCollapsed && 'flex-col gap-2'">
        <a href="#dashboard" :aria-label="t('app.title')" class="flex min-w-0 items-center gap-2 rounded-md font-semibold tracking-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <img :src="brandLogoUrl" alt="" width="32" height="32" class="size-8 shrink-0" />
          <span v-if="!sidebarCollapsed">{{ t("app.title") }}</span>
        </a>
        <Button
          variant="ghost"
          size="icon"
          @click="sidebarCollapsed = !sidebarCollapsed"
          ><PanelLeftOpen
            v-if="sidebarCollapsed"
            class="size-4" /><PanelLeftClose v-else class="size-4"
        /></Button>
      </div>
      <SidebarNav class="min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]" :collapsed="sidebarCollapsed" :active-path="activePath" />
    </aside>
    <main class="min-w-0">
      <div
        v-if="gatewayUnavailable"
        class="border-b border-amber-500/20 bg-amber-500/10 px-6 py-2 text-xs text-amber-700 dark:text-amber-300"
      >
        {{ t("app.gatewayUnavailable") }} В· {{ error }}
      </div>
      <header
        class="sticky top-0 z-20 flex h-14 items-center border-b border-border bg-background/90 px-6 backdrop-blur"
      >
        <a
          href="#dashboard"
          :title="bootstrap.node.hostname"
          class="mr-4 text-sm font-semibold capitalize"
          >{{ bootstrap.node.id }}</a
        >
        <div class="text-sm text-muted-foreground">{{ current.label }}</div>
        <div class="ml-auto flex items-center gap-2">
          <RealtimeStatus /><span class="mr-2 text-xs text-muted-foreground">{{
            accountName
          }}</span
          ><Button variant="ghost" size="icon" @click="toggleTheme"
            ><Sun v-if="theme === 'dark'" class="size-4" /><Moon
              v-else
              class="size-4" /></Button
          ><Button variant="outline" size="sm" @click="login(true)">{{
            t("app.switchAccount")
          }}</Button>
        </div>
      </header>
      <div class="mx-auto max-w-[1600px] p-6">
        <component
          v-if="serviceAvailable"
          :is="current.component"
          :key="current.id"
          v-bind="current.props"
        />
        <div v-else class="space-y-4">
          <p
            role="status"
            class="rounded-lg border border-border bg-muted p-4 text-sm"
          >
            {{
              t("services.unavailableRoute", {
                name: selectedService?.name || selectedServiceId,
              })
            }}
          </p>
          <ServicesPage />
        </div>
      </div>
    </main>
  </div>
  <div
    v-else
    class="grid min-h-screen place-items-center bg-background p-6 text-sm text-destructive"
  >
    {{ error || t("app.unavailable") }}
  </div>
</template>
