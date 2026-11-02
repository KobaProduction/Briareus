/** Protected workspace components stay behind explicit lazy entrypoints. */
export function loadPlatformAdministration() {return import("./ui/PlatformAdministration.vue");}
export function loadAgentsWorkspace() {return import("./ui/AgentsWorkspace.vue");}
export function loadTerminalWorkspace() {return import("./ui/TerminalWorkspace.vue");}
export function loadFilesWorkspace() {return import("./ui/FilesWorkspace.vue");}
export function loadBrowserWorkspace() {return import("./ui/BrowserWorkspace.vue");}
export function loadAuthorizationOverview() {return import("./ui/AuthorizationOverview.vue");}
export function loadAnalysisWorkspace() {return import("./ui/AnalysisWorkspace.vue");}
export function loadScopedSessionsWorkspace() {return import("./ui/ScopedSessionsWorkspace.vue");}
export function loadSignalsWorkspace() {return import("./ui/SignalsWorkspace.vue");}
export function loadPlatformContextView() {return import("./ui/PlatformContextView.vue");}
export function loadApprovalQueue() {return import("./ui/ApprovalQueue.vue");}
export function loadOpenNormalSession() {return import("./ui/OpenNormalSession.vue");}
export function loadOidcProjectWorkspace() {return import("./ui/OidcProjectWorkspace.vue");}
export function loadCurrentAgentSessions() {return import("./ui/CurrentAgentSessions.vue");}
