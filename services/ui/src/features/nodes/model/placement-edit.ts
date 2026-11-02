import type {ResourceLimits} from '@/entities/node'
import type {ModuleConfiguration} from './module-configuration'
import {initialConfiguration} from './module-configuration'
import type {ProjectWorkspaceMount} from './project-workspace'
import {projectWorkspaceField} from './project-workspace'

interface Release {id:string;image:string}
interface EditablePlacement {
 module:string;state:string;release_uuid:string;limits:ResourceLimits
 configuration?:ModuleConfiguration|null;project_workspace?:ProjectWorkspaceMount|null
}

/** Opening an editor never chooses an upgrade or downgrade on the user's behalf. */
export function currentPlacementRelease(id:string,releases:readonly Release[]):string {
 return releases.some(release=>release.id===id)?id:''
}

/** Keep the original wire configuration when the form only materializes defaults. */
export function placementConfigurationField(module:string,original:ModuleConfiguration|null|undefined,current:ModuleConfiguration):{configuration?:ModuleConfiguration} {
 if(!['web','serena'].includes(module))return {}
 return JSON.stringify(initialConfiguration(module,original))===JSON.stringify(initialConfiguration(module,current))?{}:{configuration:current}
}

export function placementHasChanges(original:EditablePlacement,release:string,releases:readonly Release[],limits:ResourceLimits,configuration:ModuleConfiguration,workspace:ProjectWorkspaceMount|null):boolean {
 // A failed instance may need recovery even when the desired content is unchanged.
 if(original.state!=='ready')return true
 const before=releases.find(item=>item.id===original.release_uuid)
 const after=releases.find(item=>item.id===release)
 if(!before||!after||before.image!==after.image)return true
 if((['memory_bytes','cpu_millis','pids'] as const).some(key=>limits[key]!==original.limits[key]))return true
 return 'configuration' in placementConfigurationField(original.module,original.configuration,configuration)||
  'project_workspace' in projectWorkspaceField(original.module,original.project_workspace,workspace,true)
}
