import { describe, expect, it } from "bun:test";
import { readFileSync } from "node:fs";

describe("server-verified resources remain lazy and fail closed", () => {
  it("never statically loads command widgets from the anonymous auth controller", () => {
    const src = readFileSync("src/pages/platform/ui/OidcPanelPage.vue", "utf8");
    const compact = src.replace(/\s+/g, "");
    const protectedModules = [
      "ConnectionsWorkspace",
      "PlatformAdministration",
      "AgentsWorkspace",
      "TerminalWorkspace",
      "FilesWorkspace",
      "BrowserWorkspace",
      "CatalogWorkspace",
      "NodesPage",
      "AuthorizationOverview",
      "AnalysisWorkspace",
      "ModuleWorkspacePage",
      "ScopedSessionsWorkspace",
      "AccountProfilePage",
      "SignalsWorkspace",
      "DashboardOverview",
      "PlatformSettingsPage",
    ] as const;
    for (const name of protectedModules) {
      expect(src).toMatch(new RegExp(`const\\s+${name}\\s*=\\s*protectedPage\\(`));
      expect(src).not.toMatch(new RegExp(`import\\s+${name}\\s+from`));
    }
    expect(compact).toContain('protectedPage(()=>import("./ModuleWorkspacePage.vue"))');
    expect(readFileSync("src/pages/platform/index.ts", "utf8")).toContain(
      'import("./ui/ModuleWorkspacePage.vue")',
    );
    expect(compact).toContain('<mainv-if="!activeContext"');
    expect(compact).toContain("<ControlPanelShellv-else");
    expect(compact).toContain('v-if="membership&&workspaceContext&&identity"');
    expect(compact).toContain(":inert=\"!activeContext||eventBus.state.status!=='connected'\"");
    expect(compact).toContain("if(current)acceptSnapshot(user,current)");
    expect(compact).toContain("elserecoverConnection()");
    expect(src).toContain("projectLease.value?.remainingMilliseconds()");
    expect(src).toContain("userLease.value?.remainingMilliseconds()");
    expect(readFileSync("src/shared/lib/protected-page.ts", "utf8")).toContain(
      "errorComponent:ProtectedSectionLoadError",
    );
    expect(readFileSync("src/shared/lib/protected-page.ts", "utf8")).toContain(
      "loadingComponent:ProtectedSectionLoadState",
    );
  });
  it("missing verified section scripts cannot become a guest, grant or automatic POST", () => {
    const src = readFileSync("src/shared/ui/ProtectedSectionLoadState.vue", "utf8");
    expect(src).toContain(":role=\"props.failed?'alert':'status'\"");
    expect(src).toContain("window.location.reload()");
    expect(src).not.toContain("fetch(");
    expect(src).not.toContain("oidc/authorize");
    expect(src).not.toContain("credentials");
  });
});
