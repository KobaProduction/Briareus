/** Public lazy entrypoints keep private authenticated pages out of the login chunk. */
export function loadOidcPanelPage(){return import("./ui/OidcPanelPage.vue")}
export function loadControlPanelAccessPage(){return import("./ui/ControlPanelAccessPage.vue")}
export function loadPlatformSettingsPage(){return import("./ui/PlatformSettingsPage.vue")}

export function loadModuleWorkspacePage(){return import("./ui/ModuleWorkspacePage.vue")}
