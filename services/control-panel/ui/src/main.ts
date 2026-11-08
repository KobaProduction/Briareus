import { createApp, defineAsyncComponent } from "vue"
import { panelPinia } from "@/shared/state/pinia"
import "@/app/styles.css"

async function bootstrap(): Promise<void> {
  const app = createApp(defineAsyncComponent(() => import("@/app/App.vue")))
  app.use(panelPinia)
  // Install persistence before importing modules that instantiate shared stores.
  const [{ i18n }, { frontendTelemetry }, { notifications }] = await Promise.all([
    import("@/shared/i18n"), import("@/shared/telemetry/client"), import("@/shared/notifications/bus"),
  ])
  app.use(i18n)
  window.addEventListener("error", event => { frontendTelemetry.error("window.error", event.error ?? event.message); notifications.error("Frontend error", event.message) })
  window.addEventListener("unhandledrejection", event => { frontendTelemetry.error("unhandledrejection", event.reason); notifications.error("Unhandled frontend error", event.reason instanceof Error ? event.reason.message : String(event.reason)) })
  frontendTelemetry.event("app.start", { language: navigator.language, user_agent_family: navigator.userAgent.includes("Chrome") ? "chromium" : "other" })
  app.mount("#app")
}

void bootstrap()
