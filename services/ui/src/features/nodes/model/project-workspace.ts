export interface ProjectWorkspaceMount {id:string;read_only:boolean}
export interface ProjectWorkspace {id:string;node_uuid:string;project_uuid:string;purpose:'workspace';retention:'persistent'}

/** Omitted update preserves the mount; explicit null detaches it. */
export function projectWorkspaceField(module:string,original:ProjectWorkspaceMount|null|undefined,current:ProjectWorkspaceMount|null,updating:boolean):{project_workspace?:ProjectWorkspaceMount|null}{
 if(!['web','reverse'].includes(module))return {}
 if(module==='reverse'&&current)current={...current,read_only:true}
 const equal=(original??null)===current||!!original&&!!current&&original.id===current.id&&original.read_only===current.read_only
 if(updating)return equal?{}:{project_workspace:current}
 return current?{project_workspace:current}:{}
}
