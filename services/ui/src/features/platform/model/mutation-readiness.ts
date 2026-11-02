import { platformPort } from "../api/port"
import { commandCoordinator } from "./command-coordinator"
import { projectContext } from "./project-context"
import type { ScopeSelection, UiCapability, SourceCommandBinding } from "./contracts"
import type { UiError } from "./errors"

function selectedTeamOwns(scope: ScopeSelection, teamId: string): boolean {
  if (scope.kind === "team") return scope.teamId === teamId
  if (scope.kind === "project") {
    const project = projectContext.state.projects.find(item => item.key === scope.projectId)
    return project?.ownership === "team" && project.ownerTeamId === teamId && project.lifecycleStatus === "active"
  }
  return scope.kind !== "account" || projectContext.state.teams.some(item => item.key === teamId)
}
function targetOwnerMatches(scope: ScopeSelection, selector: string | SourceCommandBinding): boolean {
  if (typeof selector === "string") return true
  const target = selector.target
  if (target.kind === "resource" && target.owner.kind === "team") return selectedTeamOwns(scope, target.owner.teamId)
  if (target.kind === "team") return selectedTeamOwns(scope, target.id)
  return true
}
/** Availability requires a real reviewed inspector; local permission cannot mint an API. */
export function sourceMutationReady(ability: UiCapability, selector: string | SourceCommandBinding | null): boolean {
  const scope = projectContext.selection()
  const principal = projectContext.state.user?.key ?? ""
  if (!platformPort.value?.bff?.inspectOriginalCommand || !scope || !principal || !selector) return false
  if (!projectContext.can(ability) || !commandCoordinator.supportedSourceBinding(scope, selector)) return false
  return !commandCoordinator.lookup(principal, scope) && targetOwnerMatches(scope, selector)
}
export function mutationBlockedIssue(selector: string | SourceCommandBinding | null): UiError {
  const pending = commandCoordinator.lookup(projectContext.state.user?.key ?? "", projectContext.selection())
  if (pending) return { kind: "uncertain", code: "original_command_still_pending", message: "outcomeUncertain" }
  if (!selector || !platformPort.value?.bff?.inspectOriginalCommand) {
    return { kind: "unavailable", code: "original_command_status_missing", message: "serverCommandStatusRequired" }
  }
  return { kind: "forbidden", code: "owner_or_scope_authority_missing", message: "ownerAuthorityRequired" }
}
