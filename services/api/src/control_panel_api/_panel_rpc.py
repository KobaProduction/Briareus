"""Panel RPC methods use existing owner commands, with no HTTP loopback proxy."""
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.responses import JSONResponse


class RpcFailure(Exception):
    def __init__(self, code, *, uncertain=False):
        self.code, self.uncertain = code, uncertain


class PanelRpc:
    def __init__(self, current_context, platform):
        self.current_context, self.platform = current_context, platform

    async def platform_call(self, socket, method, params):
        from ._platform_management import PlatformCommand
        current = await self.current_context(socket)
        if isinstance(current, JSONResponse):
            raise RpcFailure("CURRENT_PLATFORM_REQUIRED")
        session, proof = current
        directory=method=='platform.directory'
        team_read=method=='platform.team'
        team_id=params.get('id') if team_read else None
        invitation=method=='platform.command' and params.get('action') in {'invitation.capabilities','invitation.issue'}
        if team_read and (set(params)!={'id'} or not proof.directory_paged and not any(str(team.team_uuid)==team_id for team in proof.teams)):
            raise RpcFailure('TEAM_MEMBERSHIP_REQUIRED')
        if not team_read and not invitation and not directory and proof.role != "operator":
            raise RpcFailure("PLATFORM_OPERATOR_REQUIRED")
        if self.platform is None:
            raise RpcFailure("PLATFORM_MANAGEMENT_UNAVAILABLE")
        mutation = method == "platform.command"
        if mutation:
            try:
                command = PlatformCommand.model_validate(params).model_dump(mode="json")
            except ValueError:
                raise RpcFailure("COMMAND_INVALID") from None
        elif directory:
            command={"operation_uuid":str(uuid4()),"action":"directory","data":params}
        elif team_read:
            command={'operation_uuid':str(uuid4()),'action':'team.read','data':{'id':team_id}}
        elif not params:
            command = {"operation_uuid": str(uuid4()), "action": "inventory", "data": {}}
        else:
            raise RpcFailure("COMMAND_INVALID")
        deadline = min(session.expires_at, proof.expires_at)
        try:
            status, result = await self.platform.management({"issuer": session.issuer,
                "subject": session.subject, **command}, expires_at=deadline)
        except Exception:
            raise RpcFailure("OPERATION_OUTCOME_UNKNOWN", uncertain=mutation) from None
        if status != 200:
            code = result.get("error", {}).get("code", "PLATFORM_MANAGEMENT_UNAVAILABLE")
            raise RpcFailure(code if isinstance(code, str) and len(code) <= 128 else "UNAVAILABLE",
                uncertain=mutation and status >= 500 and code not in {
                    'RAUTHY_INVITATION_MAIL_UNCONFIGURED','RAUTHY_INVITATION_KEY_UNAVAILABLE'})
        fresh = await self.current_context(socket)
        if (isinstance(fresh, JSONResponse) or deadline <= datetime.now(UTC)
            or fresh[1].user_uuid != proof.user_uuid
            or (not team_read and not invitation and not directory and fresh[1].role != 'operator')
            or (team_read and (fresh[1].role != proof.role or not fresh[1].directory_paged and not any(str(team.team_uuid)==team_id for team in fresh[1].teams)))):
            raise RpcFailure("OPERATION_OUTCOME_UNKNOWN", uncertain=mutation)
        return result
