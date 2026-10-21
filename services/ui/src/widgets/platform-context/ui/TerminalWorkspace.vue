<script setup lang="ts">
import {useLiveQuery} from "@/shared/lib/use-live-query"
import SessionPicker from "@/features/agent-sessions/ui/SessionPicker.vue"
import {computed,onBeforeUnmount,ref,watch} from "vue"
import {listCurrentSessions,type CurrentAgentSession} from "@/features/agent-sessions"
import {requestSessionElevation} from "@/features/approvals"
import type {VerifiedPlatformContext} from "@/entities/workspace/model/proof"
import {parseHandEffectScopes,type HandEffectScope} from "@/shared/lib/hand-effect-scope"
import {eventBus} from "@/shared/events/bus"
import {Button} from "@/shared/ui/button"
import {Input} from "@/shared/ui/input"
import {Card,CardContent,CardHeader,CardTitle} from "@/shared/ui/card"

const props=defineProps<{context:VerifiedPlatformContext;selectedProjectId:string|null}>()
const emit=defineEmits<{selectProject:[id:string];openSessions:[]}>()
const resources=ref<HandEffectScope[]>([]),sessions=ref<CurrentAgentSession[]>([])
const selected=ref(""),command=ref(""),output=ref(""),notice=ref(""),busy=ref(false)
const approvalPending=ref(false)
const project=computed(()=>props.context.projects.find(p=>p.id===props.selectedProjectId))
const chosen=computed(()=>sessions.value.find(s=>s.session_uuid===selected.value))
const allowed=computed(()=>chosen.value?.status==="active"&&chosen.value.created_by_user_uuid===props.context.user.id&&
  Date.parse(chosen.value.hard_expires_at)>Date.now()&&["terminal_status","workspace_create","job_start","job_read","job_cancel"].every(tool=>chosen.value!.resources.some(scope=>scope.hand==="terminal"&&
  scope.tool===tool&&scope.action==="terminal.execute"&&resources.value.some(actual=>actual.tool===scope.tool&&actual.resource.id===scope.resource.id))))
let controller:AbortController|null=null,generation=0
let pending:{operation_uuid:string;project_uuid:string;agent_session_uuid:string;expected_grant_revision:number;tool:string;arguments:Record<string,unknown>}|null=null
const pendingCommand=ref(false)
const activeJob=ref("")
const identityKey=computed(()=>JSON.stringify([props.context.rauthy.issuer,props.context.rauthy.subject,
  props.context.user.id,props.selectedProjectId]))
const storageKey=computed(()=>"briareus-terminal-intent:"+identityKey.value)
function explain(code:string):string{
  if(code.includes("PERMISSION")||code.includes("HTTP_403"))return "Нет действующего разрешения на терминал. Проверьте выбранный сеанс и согласование."
  if(code.includes("REVISION")||code.includes("CONFLICT"))return "Права сеанса изменились. Обновите подключение."
  if(code.includes("SCOPE")||code.includes("INVALID"))return "Сервер не подтвердил выбранный ресурс или параметры. Обновите подключение."
  if(code.includes("OUTCOME")||code.includes("UNCERTAIN"))return "Результат операции пока не подтверждён."
  return "Исполнитель этого проекта недоступен. Обновите подключение или выберите другой проект."
}
function commandOutput(value:unknown):string{
  if(!value||typeof value!=="object")return "Ответ команды не подтверждён."
  const result=value as {structuredContent?:Record<string,unknown>;content?:{type:string;text?:string}[]}
  let data=result.structuredContent
  const text=result.content?.filter(item=>item.type==="text").map(item=>item.text??"").join("\n")??""
  if(!data){try{data=JSON.parse(text)}catch{return text}}
  if(data&&typeof data.stdout==="string"&&typeof data.stderr==="string"){
    return data.stdout+data.stderr+"\nКод завершения: "+String(data.exit_code)+(data.timed_out?" · Лимит времени исчерпан":"")
  }
  return text||JSON.stringify(data??value,null,2)
}

async function load():Promise<void>{
  if(!project.value||busy.value)return
  controller?.abort();const request=new AbortController();controller=request
  const run=++generation,scope=project.value.id,actor=props.context.user.id
  notice.value=""
  try{
    const raw=await eventBus.request<{items:unknown}>("terminal.resources",{project_uuid:scope},request.signal)
    const found=parseHandEffectScopes(raw.items,["terminal.execute"],scope)
    if(!found||found.some(item=>item.hand!=="terminal"))throw new Error("RUNTIME_SCOPE_INVALID")
    const inventory=await listCurrentSessions(scope,actor,project.value.permissions.includes("approve_agent_session"),request.signal)
    if(run!==generation)return
    if(inventory.kind!=="ready")throw new Error(inventory.code)
    resources.value=found
    sessions.value=inventory.items.filter(item=>item.created_by_user_uuid===actor&&item.status==="active"&&Date.parse(item.hard_expires_at)>Date.now())
    if(pending&&sessions.value.some(item=>item.session_uuid===pending!.agent_session_uuid))selected.value=pending.agent_session_uuid
    else if(!sessions.value.some(item=>item.session_uuid===selected.value)){
      selected.value=(sessions.value.find(item=>item.is_elevated&&item.operations.includes("terminal.execute"))??sessions.value[0])?.session_uuid??""
    }
  }catch(error){if(run===generation){resources.value=[];sessions.value=[];notice.value=explain(error instanceof Error?error.message:"RUNTIME_OWNER_UNAVAILABLE")}}
}

async function requestAccess():Promise<void>{
  if(!chosen.value||!resources.value.length||busy.value||approvalPending.value)return
  busy.value=true;notice.value="";const run=generation,request=new AbortController();controller=request
  try{
    const result=await requestSessionElevation(chosen.value,resources.value,300,props.context.user.id,request.signal)
    if(run!==generation)return
    if(result.kind==="pending"){
      approvalPending.value=true;notice.value="Запрос отправлен в согласования. Его должен подтвердить другой участник с правом одобрения."
    }else{
      if(result.kind==="uncertain")approvalPending.value=true
      notice.value=explain(result.code)
    }
  }finally{if(run===generation)busy.value=false}
}

async function execute():Promise<void>{
  if(!project.value||!chosen.value||busy.value||!allowed.value||(!pending&&!command.value.trim()))return
  const recovering=!!pending
  if(!pending){
    pending={operation_uuid:crypto.randomUUID(),project_uuid:project.value.id,
      agent_session_uuid:chosen.value.session_uuid,expected_grant_revision:chosen.value.revision,
      tool:"job_start",arguments:{workspace_id:"default",command:command.value,interactive:false}}
    sessionStorage.setItem(storageKey.value,JSON.stringify(pending));pendingCommand.value=true
  }
  busy.value=true;notice.value="";const run=generation,request=new AbortController();controller=request

  try{
    if(!activeJob.value){
      const workspace=!recovering?await eventBus.request<{isError?:boolean}>("terminal.command",{...pending,operation_uuid:crypto.randomUUID(),tool:"workspace_create",arguments:{workspace_id:"default"}},request.signal):{}
      if(workspace.isError)throw new Error("TERMINAL_OPERATION_FAILED")
      const result=await eventBus.request<unknown>("terminal.command",pending!,request.signal)
      const body={operation_uuid:pending!.operation_uuid,result}
    if(run!==generation)return
    if(body.operation_uuid!==pending.operation_uuid)throw new Error("TERMINAL_OUTCOME_UNKNOWN")
    const data=body.result as {structuredContent?:Record<string,unknown>;content?:{text?:string}[];isError?:boolean}
    if(data.isError)throw new Error("TERMINAL_OPERATION_FAILED")
    const started=data.structuredContent??JSON.parse(data.content?.[0]?.text??"{}")
    if(typeof started.job_id!=="string")throw new Error("TERMINAL_OUTCOME_UNKNOWN")
    activeJob.value=started.job_id;output.value=""
    sessionStorage.setItem(storageKey.value,JSON.stringify({...pending,job_id:activeJob.value}))
    }
    output.value=""
    let cursor=0
    while(run===generation&&activeJob.value){
      const polling={...pending,operation_uuid:crypto.randomUUID(),tool:"job_read",arguments:{job_id:activeJob.value,cursor,max_bytes:65536,wait_seconds:0}}
      const raw={result:await eventBus.request<{structuredContent?:Record<string,unknown>;content?:{text?:string}[];isError?:boolean}>("terminal.command",polling,request.signal)}
      if(run!==generation)return
      if((raw.result as {isError?:boolean}).isError)throw new Error("TERMINAL_OPERATION_FAILED")
      const result=raw.result.structuredContent??JSON.parse(raw.result.content?.[0]?.text??"{}")
      output.value=(output.value+String(result.output??"")).slice(-1048576)
      cursor=Number(result.next_cursor??cursor)
      if(result.eof===true){notice.value="Команда завершена: "+String(result.state);activeJob.value="";break}
      await new Promise<void>(resolve=>setTimeout(resolve,1000))
    }
    pending=null;activeJob.value="";pendingCommand.value=false;sessionStorage.removeItem(storageKey.value)
  }catch(error){if(run===generation)notice.value=explain(error instanceof Error?error.message:"TERMINAL_OUTCOME_UNKNOWN")+" Если идентификатор задания получен, можно продолжить чтение. Не повторяйте запуск с неподтверждённым результатом."}
  finally{if(run===generation)busy.value=false}
}

async function cancelJob():Promise<void>{
  if(!activeJob.value||!pending)return
  const run=generation
  const intent={...pending,operation_uuid:crypto.randomUUID(),tool:"job_cancel",arguments:{job_id:activeJob.value,grace_seconds:0.5}}
  try{
    const result=await eventBus.request<{isError?:boolean}>("terminal.command",intent)
    if(result.isError&&run===generation)notice.value="Не удалось подтвердить остановку задания."
  }catch{if(run===generation)notice.value="Результат остановки не подтверждён."}
}

function newCommand():void{
  if(busy.value)return
  pending=null;activeJob.value="";pendingCommand.value=false;sessionStorage.removeItem(storageKey.value)
  command.value="";notice.value="Исходный результат остаётся неподтверждённым. Новая команда создаст отдельную операцию."
}

watch(identityKey,()=>{
  controller?.abort();++generation;busy.value=false;approvalPending.value=false
  resources.value=[];sessions.value=[];selected.value="";output.value="";command.value="";pending=null;pendingCommand.value=false;activeJob.value=""
  try{
    const saved=sessionStorage.getItem(storageKey.value)
    if(saved&&saved.length<=32768){
      const value=JSON.parse(saved)
      if(value.project_uuid===props.selectedProjectId&&value.tool==="job_start"&&typeof value.arguments?.command==="string"){
        pending={operation_uuid:value.operation_uuid,project_uuid:value.project_uuid,agent_session_uuid:value.agent_session_uuid,
          expected_grant_revision:value.expected_grant_revision,tool:value.tool,arguments:value.arguments}
        command.value=value.arguments.command;pendingCommand.value=true
        if(typeof value.job_id==="string"&&/^[a-f0-9]{32}$/.test(value.job_id))activeJob.value=value.job_id
      }
    }
  }catch{/* Malformed local recovery state never becomes execution authority. */}
  
},{immediate:true})
onBeforeUnmount(()=>{controller?.abort();++generation})
const liveQuery=useLiveQuery(load,{enabled:()=>!!project.value,paused:()=>busy.value,topics:['access.sessions','management.events'],accept:event=>(event.data as Record<string,unknown>|null)?.project_id===props.selectedProjectId})
watch(identityKey,()=>liveQuery.invalidate())
</script>

<template>
  <Card class="min-w-0">
    <CardHeader><CardTitle>Терминал проекта</CardTitle></CardHeader>
    <CardContent class="space-y-4">
      
      <div class="flex flex-wrap gap-2">
        
        <Button variant="outline" :disabled="busy" @click="emit('openSessions')">Сессии и согласования</Button>
      </div>
      <p v-if="!project" role="status">Выберите проект.</p>
      <template v-else>
        <p v-if="resources.length" class="text-sm text-muted-foreground">Исполнитель проекта подключён. Доступно инструментов: {{resources.length}}.</p>
        <label class="block text-sm">Сеанс выполнения
          <SessionPicker v-model="selected" :items="sessions" :disabled="busy||pendingCommand"/>
        </label>
        <Button v-if="chosen&&!allowed" variant="outline" :disabled="busy||!resources.length||approvalPending" @click="requestAccess">Запросить доступ к терминалу на 5 минут</Button>
        <label class="block text-sm">Команда
          <Input v-model="command" class="mt-1 font-mono" placeholder="Например: pwd" :disabled="busy||pendingCommand" @keydown.enter="execute"/>
        </label>
        <p class="text-xs text-muted-foreground">Фоновое задание. Лимит времени задаётся настройками ноды или сервера.</p>
        <Button :disabled="busy||!allowed||(!command.trim()&&!pendingCommand)" @click="execute">{{busy?'Выполняется…':pendingCommand?(activeJob?'Продолжить чтение':'Уточнить запуск'):'Выполнить'}}</Button>
        <Button v-if="activeJob" variant="outline" @click="cancelJob">Остановить</Button>
        <Button v-if="pendingCommand" variant="outline" :disabled="busy" @click="newCommand">Новая команда</Button>
        <pre v-if="output" aria-label="Вывод команды" class="max-h-96 overflow-auto whitespace-pre-wrap rounded-md border bg-muted/30 p-3 text-xs">{{output}}</pre>
      </template>
      <p v-if="notice" role="status" class="break-words text-sm">{{notice}}</p>
    </CardContent>
  </Card>
</template>
