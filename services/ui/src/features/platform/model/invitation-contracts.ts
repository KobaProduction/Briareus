export interface InvitationCapabilities {can_invite:boolean;can_manage_inviters:boolean;inviter_ids:string[];unavailable_reason:string|null}
export type InvitationCommand={operation_uuid:string}&({action:"invitation.issue";data:{email:string}}|{action:"inviter.set";data:{user_id:string;enabled:boolean}});
export interface InvitationPort {capabilities(signal:AbortSignal):Promise<InvitationCapabilities>;command(command:InvitationCommand,signal:AbortSignal):Promise<void>;onChange(listener:()=>void):()=>void}
