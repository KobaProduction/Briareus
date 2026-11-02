import { projectContext } from "./project-context"
import type { ScopeSelection } from "./contracts"

export function verifiedDecisionVersion(scope: ScopeSelection): string | null {
  if (scope.kind === "project") return projectContext.state.projectDecisionVersions[scope.projectId] ?? null
  if (scope.kind === "team") return projectContext.state.teamDecisionVersions[scope.teamId] ?? null
  return null
}
/** A response must retain both the selected UUID and the authority epoch. */
export function sameScope(expected: ScopeSelection, revision: number): boolean {
  const selected = projectContext.selection()
  if (revision !== projectContext.state.revision || !selected || selected.kind !== expected.kind) return false
  if (selected.kind === "project") return expected.kind === "project" && selected.projectId === expected.projectId
  if (selected.kind === "team") return expected.kind === "team" && selected.teamId === expected.teamId
  return true
}
