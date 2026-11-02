import { canonicalUuid4, type ScopeSelection, type SourceCommandBinding, type SourceCommandTarget } from "./contracts"

const projectCommands = new Set(["agent.create", "session.open", "project.transfer_owner", "project.admin_reassign"])
const resourceCreates = new Set(["integration.create", "variable.create"])
const resourceEdits = new Set(["integration.update", "integration.rotate", "integration.revoke",
  "variable.update", "variable.rotate", "variable.revoke"])
const scopedCommand = /^(?:agent\.(?:rename|state)|session\.(?:elevation|resolve|revoke)):(?:[0-9a-f]{8}-){1}[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function projectOperation(scope: ScopeSelection, operation: string, id: string): boolean {
  if (scope.kind === "project") return scope.projectId === id &&
    (projectCommands.has(operation) || scopedCommand.test(operation))
  return scope.kind === "operator" && ["project.admin_reassign", "project.transfer_owner"].includes(operation)
}
function teamOperation(scope: ScopeSelection, operation: string, id: string, teamOperations: readonly string[]): boolean {
  const matchesScope = scope.kind === "team" ? scope.teamId === id :
    ["project", "account", "operator"].includes(scope.kind)
  return matchesScope && (resourceCreates.has(operation) || teamOperations.includes(operation))
}
function resourceOperation(scope: ScopeSelection, operation: string,
  target: Extract<SourceCommandTarget, { kind: "resource" }>): boolean {
  if (!resourceEdits.has(operation) || !(scope.kind === "team" || scope.kind === "project")) return false
  const owner = target.owner
  if (owner.kind === "team") return canonicalUuid4(owner.teamId) &&
    (scope.kind !== "team" || scope.teamId === owner.teamId)
  return scope.kind === "project" && owner.projectId === scope.projectId
}
function acceptedBinding(scope: ScopeSelection, binding: SourceCommandBinding, teamOperations: readonly string[]): boolean {
  const { operation, target } = binding
  if (!canonicalUuid4(target.id)) return false
  switch (target.kind) {
    case "project": return projectOperation(scope, operation, target.id)
    case "project_resource": return scope.kind === "project" &&
      scope.projectId === target.id && resourceCreates.has(operation)
    case "team": return teamOperation(scope, operation, target.id, teamOperations)
    case "resource": return resourceOperation(scope, operation, target)
  }
}
/** Selector validation never grants permission or creates an owner endpoint. */
export function checkedSourceBinding(scope: ScopeSelection,
  requested: string | SourceCommandBinding | null, teamOperations: readonly string[]): SourceCommandBinding | null | false {
  if (requested === null) return null
  const selected: SourceCommandBinding = typeof requested === "string" ? {
    operation: requested, target: { kind: "project", id: scope.kind === "project" ? scope.projectId : "" },
  } : requested
  return acceptedBinding(scope, selected, teamOperations) ? selected : false
}
