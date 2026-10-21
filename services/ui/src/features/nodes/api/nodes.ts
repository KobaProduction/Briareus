import {eventBus} from '@/shared/events/bus'
import {isPlatformProjectId} from '@/features/platform/api/platform-current'
import type {ManagedNode} from '@/entities/node/model/types'

export async function nodeInventory(projectUuid:string):Promise<ManagedNode[]>{
  const data=await eventBus.request<{items:ManagedNode[];truncated:boolean}>('nodes.inventory',{project_uuid:projectUuid})
  if(!Array.isArray(data.items)||data.items.length>100||data.items.some(row=>!isPlatformProjectId(row.id)||typeof row.name!=='string'||typeof row.sequence!=='number'))throw new Error('NODE_RESPONSE_INVALID')
  return data.items
}
export async function nodeCommand<T=unknown>(projectUuid:string,command:Record<string,unknown>){
  return eventBus.request<T>('nodes.command',{...command,project_uuid:projectUuid})
}
