import { describe, expect, test } from "bun:test"
import { computed } from "vue"
import { createI18n } from "vue-i18n"
import { ControlPanelApiError, unavailableServiceMessage } from "../src/shared/api/error"
import { IdentityCallbackError, IdentityError, panelFailure } from "../src/shared/auth/errors"
import en from "../src/shared/i18n/locales/en"
import ru from "../src/shared/i18n/locales/ru"

describe("localized sign-in failures", () => {
  test("all user-facing failure reasons exist in both languages and react to locale changes", () => {
    const i18n = createI18n({ legacy: false, locale: "ru", fallbackLocale: "en", messages: { ru, en } })
    const failures = [
      ...(["accessDenied", "loginRequired", "interactionRequired", "providerUnavailable", "configuration", "callback"] as const).map(code => new IdentityError(code)),
      new ControlPanelApiError("private error", "http", 401),
      new ControlPanelApiError("private error", "http", 403),
      new ControlPanelApiError("private error", "http", 403, "access_denied"),
      new ControlPanelApiError("private error", "http", 503),
      new ControlPanelApiError("private error", "http", 503, "service_unavailable"),
      new ControlPanelApiError("private error", "network"),
      new Error("private error with token"),
    ]
    for (const failure of failures) {
      const key = panelFailure(failure).messageKey
      expect(i18n.global.te(key, "ru")).toBe(true)
      expect(i18n.global.te(key, "en")).toBe(true)
      i18n.global.locale.value = "ru"
      const message = computed(() => i18n.global.t(key))
      const russian = message.value
      expect(russian).toMatch(/[А-Яа-я]/)
      i18n.global.locale.value = "en"
      expect(message.value).not.toBe(russian)
      expect(message.value).not.toMatch(/[А-Яа-я]/)
      expect(message.value).not.toContain("private")
    }
  })

  test("callback reasons use protocol codes, never untrusted descriptions or exception text", () => {
    for (const [code, key] of [
      ["access_denied", "accessDenied"], ["login_required", "loginRequired"],
      ["consent_required", "interactionRequired"], ["interaction_required", "interactionRequired"],
      ["account_selection_required", "interactionRequired"], ["server_error", "providerUnavailable"],
      ["temporarily_unavailable", "providerUnavailable"], ["unknown-vendor-code", "callback"],
    ]) {
      const failure = panelFailure(new IdentityCallbackError({ error: code, error_description: "secret <script>" }))
      expect(failure).toEqual({ messageKey: `authErrors.${key}`, retry: false, requestId: "" })
    }
    expect(panelFailure(new IdentityCallbackError(new Error("access_denied"))).messageKey).toBe("authErrors.callback")
  })

  test("access denial is not gateway downtime; support IDs are bounded and sanitized", () => {
    expect(panelFailure(new ControlPanelApiError("unauthorized", "http", 401)).retry).toBe(false)
    expect(panelFailure(new ControlPanelApiError("forbidden", "http", 403)).retry).toBe(false)
    expect(panelFailure(new ControlPanelApiError("unavailable", "http", 503)).retry).toBe(true)
    expect(panelFailure(new ControlPanelApiError("secret", "http", 403, "", "request-123")).requestId).toBe("request-123")
    expect(panelFailure(new ControlPanelApiError("secret", "http", 403, "", "<html>\nsecret")).requestId).toBe("")
  })
})


test("provider disconnect errors are localized without raw protocol details and retain their outage classification",()=>{
  const i18n=createI18n({legacy:false,locale:'ru',fallbackLocale:'en',messages:{ru,en}})
  const translate=(key:string,values?:Record<string,string>)=>i18n.global.t(key,values??{})
  for(const locale of ['ru','en'] as const){
    i18n.global.locale.value=locale
    const message=unavailableServiceMessage('service_unavailable','playwright',translate)!
    expect(message).toContain('Playwright')
    expect(message).not.toContain('service_unavailable')
    expect(message).not.toContain('{')
    expect(/[А-Яа-я]/.test(message)).toBe(locale==='ru')
    expect(unavailableServiceMessage('service_unavailable','custom-provider',translate)).toContain('custom-provider')
    const unsafe=unavailableServiceMessage('service_unavailable','secret <script>',translate)!
    expect(unsafe).toBe(i18n.global.t('apiErrors.serviceUnavailable'))
    expect(unsafe).not.toContain('secret')
  }
  expect(unavailableServiceMessage('different_error','playwright',translate)).toBeNull()
  expect(panelFailure(new ControlPanelApiError('private detail','http',503,'service_unavailable'))).toEqual({messageKey:'apiErrors.serviceUnavailable',retry:true,requestId:''})
})
