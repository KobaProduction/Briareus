/** Standalone actual-widget fixture for local expiry acceptance. The browser
 * harness supplies all API replies; no application route imports this entry.
 */
import { createApp, defineAsyncComponent, h, reactive } from "vue";
import { createI18n } from "vue-i18n";
import { CatalogWorkspace } from "../../src/widgets/catalog";
import { loadCurrentAgentSessions, loadApprovalQueue } from "../../src/widgets/platform-context";
const CurrentAgentSessions = defineAsyncComponent(loadCurrentAgentSessions);
const ApprovalQueue = defineAsyncComponent(loadApprovalQueue);
import type { VerifiedPlatformContext } from "../../src/entities/workspace";
import "../../src/app/styles.css";
const state = reactive<{
  mode: "catalog" | "sessions" | "approvals";
  proof: VerifiedPlatformContext | null;
}>({ mode: "catalog", proof: null });
const i18n = createI18n({ legacy: false, locale: "ru", messages: { ru: {}, en: {} } });
createApp({
  setup: () => () => {
    const proof = state.proof,
      project = proof?.projects[0];
    if (!proof || !project) return h("p", "No proof fixture loaded");
    if (state.mode === "catalog")
      return h(CatalogWorkspace, {
        kind: "integration",
        context: proof,
        selectedProjectId: project.id,
      });
    const props = {
      projectId: project.id,
      actorId: proof.user.id,
      proofExpiresAt: proof.expires_at,
      canApprove: true,
      verifyApprover: async () => "authorized" as const,
    };
    return state.mode === "sessions"
      ? h(CurrentAgentSessions, { ...props, canList: true })
      : h(ApprovalQueue, { ...props, canRead: true });
  },
})
  .use(i18n)
  .mount("#fixture");
Object.assign(window, { __proofFixture: { state } });
