/** Port of HTTP Bridge account-draft.ts (repair branch b89c5f6).
 * Draft comparison never serializes credentials into dirty-state snapshots.
 */
export type ConnectionProvider="github"|"gitlab"|"signoz"|"coolify"
export interface GitPolicy {protected_branches:string[];required_checks?:string[];required_reviewers?:string[];local_first_guidance:boolean;local_git_transport_enabled:boolean;remote_source_mutations_enabled:boolean}
export interface ConnectionDraft {
  name:string;provider:ConnectionProvider;auth_type:string;base_url:string;
  external_id:string;ca_cert_pem:string;credential:string;git_policy?:GitPolicy
}
export const connectionProviders={
  github:{title:"GitHub",description:"Репозитории, ветки и pull request",auth:["github_token","github_app"],endpoint:"https://api.github.com"},
  gitlab:{title:"GitLab",description:"Репозитории, merge request и CI/CD",auth:["private_token","bearer","job_token"],endpoint:"https://gitlab.com"},
  signoz:{title:"SigNoz",description:"Метрики, журналы и трассировки",auth:["signoz_api_key"],endpoint:""},
  coolify:{title:"Coolify",description:"Развёртывание и управление Development",auth:["coolify_api_token"],endpoint:"https://coolify.koba-nexus.ru"},
} as const
export function newConnectionDraft(provider:ConnectionProvider):ConnectionDraft{
  return {name:"",provider,auth_type:connectionProviders[provider].auth[0],base_url:connectionProviders[provider].endpoint,
    external_id:"",ca_cert_pem:"",credential:"",...(["github","gitlab"].includes(provider)?{git_policy:{protected_branches:[],...(provider==="github"?{required_checks:["test","docker"],required_reviewers:[]}:{}),local_first_guidance:true,local_git_transport_enabled:true,remote_source_mutations_enabled:false}}:{})}
}
export function normalizeConnectionDraft(draft:ConnectionDraft){
  return {name:draft.name.trim(),provider:draft.provider,auth_type:draft.auth_type,
    base_url:draft.base_url.trim().replace(/\/+$/, ""),external_id:draft.external_id.trim(),
    git_policy:draft.git_policy,ca_cert_pem:draft.ca_cert_pem.trim(),credential_changed:Boolean(draft.credential.trim())}
}
export function connectionDraftDirty(current:ConnectionDraft,baseline:ConnectionDraft){
  return JSON.stringify(normalizeConnectionDraft(current))!==JSON.stringify(normalizeConnectionDraft(baseline))
}
export function connectionConfiguration(draft:ConnectionDraft):Record<string,unknown>{
  return {provider:draft.provider,name:draft.name.trim(),auth_type:draft.auth_type,
    base_url:draft.base_url.trim(),ca_cert_pem:draft.ca_cert_pem,...(draft.git_policy?{git_policy:draft.git_policy}:{}),
    ...(draft.provider==="github"?{external_id:draft.auth_type==="github_app"?draft.external_id.trim():""}:{})}
}
