import {eventBus} from "@/shared/events/bus"
import {RpcError} from "@/shared/events/protocol"

import type {PlatformPerson} from "@/entities/user/model/types"
import type {ManagedTeam} from "@/entities/team/model/types"
import type {ManagedProject} from "@/entities/project/model/types"
export type {PlatformPerson,ManagedTeam,ManagedProject}
export interface PlatformInventory {users:PlatformPerson[];teams:ManagedTeam[];projects:ManagedProject[];truncated:boolean}
export type ManagementAction="team.create"|"team.rename"|"team.member.add"|"team.member.remove"|"project.create"|"project.rename"
export interface PlatformCommand {operation_uuid:string;action:ManagementAction;data:Record<string,unknown>}
export class PlatformCommandFailure extends Error {
  constructor(public code:string,public uncertain:boolean){super(code)}
}
export async function platformInventory(signal:AbortSignal,teamId?:string):Promise<PlatformInventory>{
  let body:PlatformInventory
  try{body=await eventBus.request<PlatformInventory>(teamId?'platform.team':"platform.inventory",teamId?{id:teamId}:{},signal)}
  catch(error){throw new PlatformCommandFailure(error instanceof RpcError?error.message:"UNAVAILABLE",false)}
  if(!Array.isArray(body.users)||!Array.isArray(body.teams)||!Array.isArray(body.projects)||body.users.length>100||body.teams.length>100||body.projects.length>100)throw new Error("Invalid inventory")
  return body
}
export async function platformCommand(command:PlatformCommand,signal:AbortSignal):Promise<void>{
  try{
    await eventBus.request("platform.command",{...command},signal)
  }catch(error){throw new PlatformCommandFailure(error instanceof RpcError?error.message:"NETWORK_UNAVAILABLE",error instanceof RpcError?error.uncertain:true)}
}
