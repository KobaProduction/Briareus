"""One serialization of an already verified Platform authority snapshot."""

def platform_context_payload(session, proof):
    return {
                "authenticated": True,
                "authority": "platform",
                "directory_paged": proof.directory_paged,
                "rauthy": {"issuer": proof.issuer, "subject": proof.subject},
                "user": {
                    "id": str(proof.user_uuid),
                    "role": proof.role,
                    "enabled": True,
                    "name": proof.name,
                    "email": proof.email,
                },
                "teams": [
                    {
                        "id": str(item.team_uuid),
                        "owner": item.owner,
                        "name": item.name,
                        "member": item.member,
                    }
                    for item in proof.teams
                ],
                "projects": [
                    {
                        "id": str(item.project_uuid),
                        "name": item.name,
                        "owner": {
                            "kind": item.owner_kind,
                            "id": str(item.owner_uuid),
                        },
                        "permissions": list(item.permissions),
                    }
                    for item in proof.projects
                ],
                "expires_at": min(proof.expires_at, session.expires_at).isoformat(),
            }
