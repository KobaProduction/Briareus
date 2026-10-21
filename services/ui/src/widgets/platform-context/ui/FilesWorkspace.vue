<script setup lang="ts">
import {useLiveQuery} from "@/shared/lib/use-live-query"
import SessionPicker from "@/features/agent-sessions/ui/SessionPicker.vue"
import {computed,onBeforeUnmount,ref,watch} from "vue"
import {listCurrentSessions,type CurrentAgentSession} from "@/features/agent-sessions"
import {requestSessionElevation} from "@/features/approvals"
import type {VerifiedPlatformContext} from "@/entities/workspace/model/proof"
import {parseHandEffectScopes,type HandEffectScope} from "@/shared/lib/hand-effect-scope"
import {eventBus} from "@/shared/events/bus"
import {browserValue} from "@/features/browser/model/browser-state"
import ConfirmationDialog from "@/shared/ui/ConfirmationDialog.vue"
import {Textarea} from "@/shared/ui/textarea"
import {readBoundedJsonResponse} from "@/shared/lib/bounded-json-response"
import {Button} from "@/shared/ui/button"
import {Input} from "@/shared/ui/input"
import {Table,TableBody,TableCell,TableHead,TableHeader,TableRow} from "@/shared/ui/table"
import {Card,CardContent,CardHeader,CardTitle} from "@/shared/ui/card"

const props=defineProps<{context:VerifiedPlatformContext;selectedProjectId:string|null}>()
const emit=defineEmits<{selectProject:[id:string];openSessions:[]}>()
type Entry={path:string;name:string;type:"file"|"directory";size_bytes:number}
const project=computed(()=>props.context.projects.find(p=>p.id===props.selectedProjectId))
const identityKey=computed(()=>JSON.stringify([props.context.rauthy.issuer,props.context.rauthy.subject,
  props.context.user.id,props.selectedProjectId]))
const resources=ref<HandEffectScope[]>([]),sessions=ref<CurrentAgentSession[]>([])
const selected=ref(""),path=ref(""),output=ref(""),notice=ref(""),busy=ref(false),pending=ref(false)
const entries=ref<Entry[]>([])
const upload=ref<File|null>(null),editing=ref(false),previewComplete=ref(false),confirmWrite=ref(false),writeBusy=ref(false)
const writeAllowed=computed(()=>resources.value.some(s=>s.action==="files.write")&&resources.value.filter(s=>s.action==="files.write").every(actual=>chosen.value?.resources.some(scope=>scope.tool===actual.tool&&scope.action===actual.action&&scope.resource.id===actual.resource.id)))
async function rawCall(tool:string,args:Record<string,unknown>){
 if(!chosen.value||!project.value)throw Error("Выберите сеанс")
 return browserValue(await eventBus.request("files.command",{operation_uuid:crypto.randomUUID(),project_uuid:project.value.id,agent_session_uuid:chosen.value.session_uuid,expected_grant_revision:chosen.value.revision,tool,arguments:args},controller?.signal))
}
async function transfer(download=false){
 if(busy.value||writeBusy.value||!path.value)return
 writeBusy.value=true;notice.value="";const run=generation
 try{
  if(download){
   const info=await rawCall("file_info",{path:path.value});if(info.size_bytes>64*1024*1024)throw Error("Для файла больше 64 MiB используйте MCP Files")
   const parts:Uint8Array[]=[];for(let offset=0;offset<info.size_bytes;offset+=12288){const part=await rawCall("file_read",{path:path.value,offset,length:12288});if(run!==generation)return;parts.push(Uint8Array.from(atob(part.data_base64),c=>c.charCodeAt(0)))}
   const object=URL.createObjectURL(new Blob(parts as BlobPart[]));const link=document.createElement("a");link.href=object;link.download=path.value.split("/").pop()||"file";link.click();setTimeout(()=>URL.revokeObjectURL(object),1000)
  }else{
   if(upload.value&&upload.value.size>64*1024*1024)throw Error("Для файла больше 64 MiB используйте MCP Files")
   const bytes=upload.value?new Uint8Array(await upload.value.arrayBuffer()):new TextEncoder().encode(output.value);if(bytes.length>64*1024*1024)throw Error("Для файла больше 64 MiB используйте MCP Files")
   for(let offset=0;offset<Math.max(bytes.length,1);offset+=12288){if(run!==generation)return;const data_base64=btoa(String.fromCharCode(...bytes.subarray(offset,offset+12288)));await rawCall("file_write",{path:path.value,data_base64,offset,truncate:offset===0,create_parents:true})}
   upload.value=null;editing.value=false;notice.value="Файл сохранён"
  }
 }catch(error){if(run===generation)notice.value=error instanceof Error?error.message:"Передача не подтверждена. Файл может быть записан частично."}finally{if(run===generation)writeBusy.value=false;confirmWrite.value=false}
}
const chosen=computed(()=>sessions.value.find(s=>s.session_uuid===selected.value))
const allowed=computed(()=>chosen.value?.status==="active"&&Date.parse(chosen.value.hard_expires_at)>Date.now()&&
  resources.value.length>0&&resources.value.filter(s=>s.action==="files.read").every(actual=>chosen.value?.resources.some(scope=>
    scope.hand==="files"&&scope.tool===actual.tool&&scope.action===actual.action&&scope.resource.id===actual.resource.id)))
let controller:AbortController|null=null,generation=0
function explain(error:unknown):string{
  const code=error instanceof Error?error.message:""
  return code.includes("403")||code.includes("PERMISSION")?
    "Нет действующего разрешения на чтение файлов. Проверьте согласование и выбранный сеанс.":
    "Файлы или указанный путь недоступны. Обновите подключение; путь должен находиться внутри проекта."
}
async function load():Promise<void>{
  if(!project.value||busy.value||writeBusy.value)return
  controller?.abort();const request=new AbortController();controller=request
  const run=++generation,scope=project.value.id,actor=props.context.user.id
  notice.value=""
  try{
    const raw=await eventBus.request<{items:unknown}>("files.resources",{project_uuid:scope},request.signal)
    const found=parseHandEffectScopes(raw.items,["files.read","files.write"],scope)
    if(!found||!found.length||found.some(item=>item.hand!=="files"))throw new Error("FILES_SCOPE_INVALID")
    const inventory=await listCurrentSessions(scope,actor,project.value.permissions.includes("approve_agent_session"),request.signal)
    if(run!==generation)return
    if(inventory.kind!=="ready")throw new Error(inventory.code)
    resources.value=found
    sessions.value=inventory.items.filter(item=>item.created_by_user_uuid===actor&&item.status==="active"&&Date.parse(item.hard_expires_at)>Date.now())
    if(!sessions.value.some(item=>item.session_uuid===selected.value))selected.value=(sessions.value.find(item=>
      item.resources.some(scope=>scope.hand==="files"))??sessions.value[0])?.session_uuid??""
  }catch(error){if(run===generation){resources.value=[];sessions.value=[];notice.value=explain(error)}}
}
async function requestAccess():Promise<void>{
  if(!chosen.value||!resources.value.length||busy.value||writeBusy.value||pending.value)return
  busy.value=true;const run=generation,request=new AbortController();controller=request
  try{
    const result=await requestSessionElevation(chosen.value,resources.value,300,props.context.user.id,request.signal)
    if(run!==generation)return
    pending.value=result.kind==="pending"||result.kind==="uncertain"
    notice.value=result.kind==="pending"?"Запрос доступа к файлам отправлен. Его должен подтвердить другой участник с правом одобрения.":
      result.kind==="uncertain"?"Состояние запроса пока не подтверждено. Проверьте согласования.":explain(new Error(result.code))
  }finally{if(run===generation)busy.value=false}
}
async function call(tool:"file_list"|"file_read"|"file_info"|"file_hash",target=path.value):Promise<void>{
  if(!chosen.value||!project.value||!allowed.value||busy.value||writeBusy.value)return
  busy.value=true;notice.value="";output.value=""
  const request=new AbortController();controller=request;const run=generation
  const operation=crypto.randomUUID(),timer=setTimeout(()=>request.abort(),15000)
  try{
    const result=await rawCall(tool,{path:target,...(tool==='file_read'?{offset:0,length:12288}:tool==='file_list'?{offset:0,limit:50}:{})})
    const body={result}
    if(run!==generation)return
    if(tool==="file_list"){
      if(!Array.isArray(body.result.entries))throw new Error("FILES_REPLY_INVALID")
      entries.value=body.result.entries;path.value=target
      while(entries.value.length<(body.result.total??entries.value.length)){const next=await rawCall("file_list",{path:target,offset:entries.value.length,limit:50});if(run!==generation)return;if(!Array.isArray(next.entries)||!next.entries.length)break;entries.value.push(...next.entries)}
    }else if(tool==="file_read"){
      previewComplete.value=(await rawCall("file_info",{path:target})).size_bytes<=12288
      if(typeof body.result.data_base64!=="string")throw new Error("FILES_REPLY_INVALID")
      output.value=new TextDecoder().decode(Uint8Array.from(atob(body.result.data_base64),ch=>ch.charCodeAt(0)))
    }else if(tool==="file_hash")output.value="SHA-256: "+body.result.sha256
    else output.value=target+" · "+body.result.type+" · "+body.result.size_bytes+" байт"
  }catch(error){if(run===generation){notice.value=explain(error);entries.value=[]}}
  finally{clearTimeout(timer);if(run===generation)busy.value=false}
}
watch(identityKey,()=>{
  controller?.abort();generation++;busy.value=false;pending.value=false;selected.value="";path.value=""
  entries.value=[];output.value="";resources.value=[];sessions.value=[];upload.value=null;editing.value=false;previewComplete.value=false;writeBusy.value=false;confirmWrite.value=false;
},{immediate:true})
onBeforeUnmount(()=>{generation++;controller?.abort()})
const liveQuery=useLiveQuery(load,{enabled:()=>!!project.value,paused:()=>busy.value||writeBusy.value,topics:['access.sessions','management.events'],accept:event=>(event.data as Record<string,unknown>|null)?.project_id===props.selectedProjectId})
watch(identityKey,()=>liveQuery.invalidate())
</script>

<template>
  <Card><CardHeader><CardTitle>Файлы проекта</CardTitle></CardHeader><CardContent class="space-y-4">
    
    <div class="flex flex-wrap gap-2">
      <Button variant="outline" :disabled="busy||writeBusy" @click="emit('openSessions')">Сессии и согласования</Button></div>
    <p v-if="resources.length" class="text-sm text-muted-foreground">Файловое хранилище подключено. Доступно чтение, список, сведения и хеш файлов.</p>
    <label class="block">Сеанс выполнения
      <SessionPicker v-model="selected" :items="sessions" :disabled="busy||writeBusy"/>
    </label>
    <Button v-if="chosen&&(!allowed||!writeAllowed)&&resources.length" :disabled="busy||writeBusy||pending" @click="requestAccess">Запросить чтение и изменение файлов на 5 минут</Button>
    <label class="block">Путь внутри проекта<Input v-model="path" :disabled="busy||writeBusy" placeholder="Пустой путь — корневая папка"/></label>
    <div class="flex flex-wrap gap-2"><Button :disabled="busy||writeBusy||!allowed" @click="call('file_list')">Открыть папку</Button>
      <Button variant="outline" :disabled="busy||writeBusy||!allowed||!path" @click="call('file_read')">Прочитать файл</Button>
      <Button variant="outline" :disabled="busy||writeBusy||!allowed||!path" @click="call('file_info')">Сведения</Button>
      <Button variant="outline" :disabled="busy||writeBusy||!allowed||!path" @click="call('file_hash')">Хеш</Button></div>
    <div class="flex flex-wrap items-center gap-2"><Button variant="outline" :disabled="busy||writeBusy||!allowed||!path" @click="transfer(true)">Скачать файл</Button><Button variant="outline" :disabled="busy||writeBusy||!writeAllowed||!path||!previewComplete" @click="editing=true">Редактировать текст</Button><label class="text-sm">Загрузить файл<Input type="file" :disabled="busy||writeBusy||!writeAllowed" @change="(event:Event)=>{upload=(event.target as HTMLInputElement).files?.[0]??null}"/></label><Button v-if="upload" :disabled="!path||writeBusy" @click="confirmWrite=true">Загрузить по указанному пути</Button></div>
    <section v-if="editing" class="space-y-2"><Textarea v-model="output" :disabled="writeBusy" aria-label="Текст файла" class="min-h-48 font-mono"/><Button :disabled="writeBusy||!writeAllowed" @click="upload=null;confirmWrite=true">Сохранить текст</Button></section>
    <p v-if="notice" role="status">{{notice}}</p>
    <Table v-if="entries.length"><TableHeader><TableRow><TableHead>Название</TableHead><TableHead>Тип</TableHead><TableHead>Размер</TableHead><TableHead>Действие</TableHead></TableRow></TableHeader>
      <TableBody><TableRow v-for="entry in entries" :key="entry.path"><TableCell>{{entry.name}}</TableCell><TableCell>{{entry.type==='directory'?'Папка':'Файл'}}</TableCell><TableCell>{{entry.size_bytes}}</TableCell>
        <TableCell><Button variant="ghost" :disabled="busy||writeBusy||!allowed" @click="call(entry.type==='directory'?'file_list':'file_read',entry.path)">Открыть</Button></TableCell></TableRow></TableBody></Table>
    <pre v-if="output" aria-label="Содержимое файла" class="overflow-auto whitespace-pre-wrap rounded border p-3 text-sm">{{output}}</pre>
    <ConfirmationDialog :open="confirmWrite" title="Записать файл?" :description="`Содержимое ${path} будет заменено. При прерывании передачи файл может быть записан частично.`" :busy="writeBusy" confirm-label="Записать" @update:open="value=>confirmWrite=value" @confirm="transfer(false)"/>
  </CardContent></Card>
</template>
