
import {computed,onBeforeUnmount,ref,watch} from "vue"
import {useI18n} from "vue-i18n"
import {eventBus} from "@/shared/events/bus"
import {useProofLifetime} from "@/shared/lib/use-proof-lifetime"
import type {VerifiedPlatformContext} from "@/entities/workspace/model/proof"
import {platformCommand,platformInventory,PlatformCommandFailure,type PlatformCommand,type PlatformInventory,type ManagedTeam,type ManagedProject,type ManagementAction} from "@/features/platform/api/platform-management"

export function usePlatformAdministration(context:()=>VerifiedPlatformContext,onChanged:()=>void){

const {locale}=useI18n()
const ru=computed(()=>locale.value==="ru")
const inventory=ref<PlatformInventory|null>(null),loading=ref(false),busy=ref(false)
const error=ref(""),notice=ref(""),teamName=ref(""),projectName=ref(""),projectTeam=ref("")
const selectedTeam=ref(""),selectedUser=ref("")
const editing=ref<{kind:"team"|"project";id:string;expected_name:string;name:string}|null>(null)
const pending=ref<PlatformCommand|null>(null)
let controller:AbortController|null=null,commandController:AbortController|null=null,revision=0
const operator=computed(()=>context().user.role==="operator")
const proofLive=useProofLifetime(()=>context().expires_at)
const ready=computed(()=>proofLive.value&&eventBus.state.status==='connected'&&(operator.value||!!selectedTeam.value&&context().teams.some(team=>team.id===selectedTeam.value)))
const blocked=computed(()=>busy.value||pending.value!==null||!ready.value)
let dirty=false
const team=computed(()=>inventory.value?.teams.find(t=>t.id===selectedTeam.value))
const candidates=computed(()=>inventory.value?.users.filter(u=>u.enabled&&!team.value?.member_ids.includes(u.id))??[])
const storageKey=()=>"briareus:platform-command:"+context().user.id
const person=(id:string)=>{const user=inventory.value?.users.find(u=>u.id===id);return user?.name||user?.email||(ru.value?"Пользователь":"User")}
const owner=(project:ManagedProject)=>project.owner_team_id?(inventory.value?.teams.find(t=>t.id===project.owner_team_id)?.name||(ru.value?"Команда":"Team")):person(project.owner_user_id||"")
const inputClass="h-9 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
const messages:Record<string,[string,string]>={
  NAME_REQUIRED:["Укажите название.","Enter a name."],NAME_INVALID:["Название должно содержать от 1 до 255 символов.","Use 1–255 characters."],
  NAME_CHANGED:["Запись уже изменена. Данные обновлены — повторите действие.","The record changed. Review refreshed data and try again."],
  RAUTHY_USER_NOT_FOUND:["Учётная запись с таким email не найдена в Rauthy.","No Rauthy account matches this email."],
  RAUTHY_USER_NOT_ACTIVE:["Учётная запись отключена или истекла.","The account is disabled or expired."],
  TEAM_OWNER_REQUIRED:["Владелец должен оставаться участником команды.","The owner must remain a team member."],
  PLATFORM_OPERATOR_REQUIRED:["Для управления нужна роль оператора.","Operator access is required."],
  USER_SUSPENDED:["Пользователь приостановлен в Platform.","The Platform user is suspended."],
  USER_ROLE_CHANGED:["Роль уже изменена. Проверьте актуальные данные.","The role changed. Review current data."],
  OPERATOR_SELF_DEMOTION_DENIED:["Нельзя снять собственные права администратора.","You cannot remove your own administrator access."],
}
function describe(value:unknown):string{
  const code=value instanceof PlatformCommandFailure?value.code:"UNAVAILABLE"
  return messages[code]?.[ru.value?0:1]||(ru.value?"Не удалось получить подтверждение сервера.":"The server could not confirm the operation.")
}
async function load():Promise<void>{
  if(loading.value||!ready.value){dirty=true;return}
  dirty=false
  controller?.abort();const request=new AbortController(),run=++revision
  controller=request;loading.value=true
  const timer=setTimeout(()=>request.abort(),8500)
  try{
    const result=await platformInventory(request.signal,operator.value?undefined:selectedTeam.value)
    if(run!==revision)return
    const projectIds=new Set(context().projects.map(project=>project.id)),teamIds=new Set(context().teams.map(team=>team.id))
    inventory.value={...result,projects:result.projects.filter(project=>projectIds.has(project.id)),teams:result.teams.filter(team=>teamIds.has(team.id))}
    if(!result.teams.some(t=>t.id===selectedTeam.value))selectedTeam.value=""
  }catch(value){if(run===revision)error.value=describe(value)}
  finally{clearTimeout(timer);if(run===revision){loading.value=false;if(dirty&&ready.value)void load()}}
}
function persist():void{
  try{if(pending.value)sessionStorage.setItem(storageKey(),JSON.stringify(pending.value));else sessionStorage.removeItem(storageKey())}catch{/* Memory still retains the original command for retry. */}
}
async function send(action:ManagementAction,data:Record<string,unknown>):Promise<boolean>{
  if(blocked.value||!operator.value)return false
  pending.value={operation_uuid:crypto.randomUUID(),action,data};persist()
  return await retry()
}
async function retry():Promise<boolean>{
  if(!pending.value||busy.value||!ready.value||!operator.value)return false
  const command=pending.value,actor=context().user.id
  busy.value=true;error.value="";notice.value=""
  const request=new AbortController();commandController=request
  const timer=setTimeout(()=>request.abort(),8500)
  try{
    await platformCommand(command,request.signal)
    if(actor!==context().user.id)return false
    pending.value=null;persist()
    teamName.value="";projectName.value="";editing.value=null;selectedUser.value=""
    notice.value=ru.value?"Изменения сохранены.":"Changes saved."
    await load();onChanged();return true
  }catch(value){
    if(actor!==context().user.id)return false
    error.value=describe(value)
    if(!(value instanceof PlatformCommandFailure)||!value.uncertain){pending.value=null;persist();await load()}
    return false
  }finally{clearTimeout(timer);busy.value=false;commandController=null}
}
function edit(kind:"team"|"project",item:ManagedTeam|ManagedProject):void{editing.value={kind,id:item.id,expected_name:item.name,name:item.name}}
async function saveName():Promise<void>{const item=editing.value;if(!item?.name.trim())return;await send(item.kind==="team"?"team.rename":"project.rename",{id:item.id,expected_name:item.expected_name,name:item.name.trim()})}
watch(()=>JSON.stringify([context().user.id,context().user.role]),()=>{
  controller?.abort();commandController?.abort();++revision
  loading.value=false;inventory.value=null;pending.value=null;editing.value=null;error.value="";notice.value=""
  try{
    const saved=JSON.parse(sessionStorage.getItem(storageKey())||"null") as PlatformCommand|null
    if(saved&&typeof saved.operation_uuid==="string"&&typeof saved.action==="string"&&saved.data&&typeof saved.data==="object")pending.value=saved
  }catch{/* Corrupt browser state is never used as authority. */}
  if(operator.value)void load()
},{immediate:true})
const stopLive=eventBus.subscribe("management.events",event=>{
  if(/^(team\.|project\.|user\.)/.test(event.type))void load()
})
const stopResync=eventBus.subscribe('system.notifications',event=>{if(event.type==='resync.required'||event.type==='source.recovered')void load()})
watch(ready,value=>{if(value)void load()})
watch(()=>JSON.stringify([context().projects.map(project=>project.id),context().teams.map(team=>team.id)]),()=>{
  if(!operator.value&&selectedTeam.value&&!context().teams.some(team=>team.id===selectedTeam.value)){inventory.value=null;selectedTeam.value=''}
  void load()
})
watch(selectedTeam,()=>{if(!operator.value){inventory.value=null;void load()}})
onBeforeUnmount(()=>{stopLive();stopResync();controller?.abort();commandController?.abort();++revision})

const ownerNames=computed(()=>Object.fromEntries([...(inventory.value?.users??[]).map(user=>[user.id,user.name||user.email||'Пользователь']),...(inventory.value?.teams??[]).map(team=>[team.id,team.name])]))
return {ru,operator,inventory,loading,busy,blocked,error,notice,teamName,projectName,projectTeam,selectedTeam,selectedUser,editing,pending,team,candidates,person,ownerNames,send,retry,edit,saveName}
}
