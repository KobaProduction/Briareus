/** Existing OidcProjectWorkspace verification, reused by aggregated lists. */
import type {RauthyPanelIdentity} from "@/features/platform/api/rauthy-oidc"
import {readProjectContext,type VerifiedPlatformContext} from "@/features/platform/api/platform-current"
export function projectVerifier(context:VerifiedPlatformContext,identity:RauthyPanelIdentity,projectId:string,action:'use_resources'|'approve_agent_session'){
  return async(signal:AbortSignal):Promise<'authorized'|'unauthorized'|'forbidden'|'unavailable'>=>{
    if(!context.projects.some(project=>project.id===projectId&&project.permissions.includes(action)))return 'forbidden'
    const live=await readProjectContext(identity,projectId,signal)
    if(live.kind==='expired'||live.kind==='signed_out')return 'unauthorized'
    if(live.kind==='not_current'||live.kind==='denied')return 'forbidden'
    if(live.kind!=='verified')return 'unavailable'
    return live.context.user.id===context.user.id&&live.context.rauthy.issuer===identity.issuer
      &&live.context.rauthy.subject===identity.subject
      &&live.context.projects.some(project=>project.id===projectId&&project.permissions.includes(action))?'authorized':'forbidden'
  }
}
