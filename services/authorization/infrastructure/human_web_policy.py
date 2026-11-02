"""Cedar policy over independently verified human project and owner facts."""

import json

from cedarpy import PolicySet, is_authorized

from authorization.domain.human_web import HumanDecision

_POLICY = PolicySet.from_str("""
permit(principal is User, action == Action::"web.access", resource is Browser)
when { context.currentProjectAccess == true && context.currentOwnerScope == true };
permit(principal is User,
       action in [Action::"files.read", Action::"files.write", Action::"terminal.execute"],
       resource is Workspace)
when { context.currentProjectAccess == true && context.currentOwnerScope == true };
permit(principal is User, action == Action::"analysis.import", resource is AnalysisProject)
when { context.currentProjectAccess == true && context.currentOwnerScope == true };
""")


class CedarHumanPolicy:
    def permits(self, decision: HumanDecision) -> bool:
        resource_type = {
            "web.access": "Browser",
            "files.read": "Workspace",
            "files.write": "Workspace",
            "terminal.execute": "Workspace",
            "analysis.import": "AnalysisProject",
        }[decision.action]
        request = {
            "principal": f"User::{json.dumps(str(decision.actor_uuid))}",
            "action": f"Action::{json.dumps(decision.action)}",
            "resource": f"{resource_type}::{json.dumps(decision.resource_id)}",
            "context": {
                "project": str(decision.project_uuid),
                "currentProjectAccess": decision.current_project_access,
                "currentOwnerScope": decision.current_owner_scope,
            },
        }
        try:
            return is_authorized(request, _POLICY, []).allowed is True
        except Exception:
            return False
