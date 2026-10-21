<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from "vue"
import {useLiveQuery} from "@/shared/lib/use-live-query"
import {Plus,RefreshCw,Trash2,PlugZap,Pencil} from "lucide-vue-next"
import type {VerifiedPlatformContext} from "@/entities/workspace/model/proof"
import {connectionProviders,type ConnectionProvider,type ConnectionDraft} from "@/features/catalog/model/connection-draft"
import BaseConnectionForm from "@/features/catalog/ui/forms/BaseConnectionForm.vue"
import {useProofLifetime} from "@/shared/lib/use-proof-lifetime"
import {readBoundedJsonResponse} from "@/shared/lib/bounded-json-response"
import {Button} from "@/shared/ui/button"
import ConfirmationDialog from "@/shared/ui/ConfirmationDialog.vue"
import {Badge} from "@/shared/ui/badge"
import {Tabs,TabsList,TabsTrigger} from "@/shared/ui/tabs"
import {Select,SelectTrigger,SelectValue,SelectContent,SelectItem} from "@/shared/ui/select"
import {Table,TableHeader,TableHead,TableRow,TableBody,TableCell} from "@/shared/ui/table"

type Connection={id:string;name:string;provider:ConnectionProvider;base_url:string;auth_type:string;revision:number;configuration:Partial<ConnectionDraft>}
const props=defineProps<{context:VerifiedPlatformContext;selectedProjectId:string|null;embedded?:boolean;initialProvider?:ConnectionProvider}>()
const emit=defineEmits<{selectProject:[id:string]}>()
const live=useProofLifetime(()=>props.context.expires_at)
const ready=computed(()=>live.value&&props.context.user.role==="operator"&&!!props.context.projects.find(
  p=>p.id===props.selectedProjectId&&p.permissions.includes("use_resources")))
// Port of GitPage/ObservabilityPage and AccountsPanel from repair b89c5f6:
// provider tabs -> shared account table -> provider-specific modal editor.
const section=ref(props.initialProvider&&["signoz","coolify"].includes(props.initialProvider)?"infrastructure":"vcs"),selectedProvider=ref<ConnectionProvider>(props.initialProvider??"github")
const providers=computed<ConnectionProvider[]>(()=>section.value==="vcs"?["github","gitlab"]:["signoz","coolify"])
const displayed=computed(()=>rows.value.filter(row=>row.provider===selectedProvider.value))
watch(section,value=>{const allowed:ConnectionProvider[]=value==="vcs"?["github","gitlab"]:["signoz","coolify"];if(!allowed.includes(selectedProvider.value))selectedProvider.value=allowed[0]!})
watch(()=>props.initialProvider,value=>{if(value){section.value=["signoz","coolify"].includes(value)?"infrastructure":"vcs";selectedProvider.value=value}})
const authLabel=(value:string)=>({github_token:"GitHub token",github_app:"GitHub App",private_token:"Private token",bearer:"Bearer token",job_token:"Job token",signoz_api_key:"API key",coolify_api_token:"API token"}[value]??value)
const rows=ref<Connection[]>([]),busy=ref(false),message=ref(""),schemaReady=ref(false)
const checks=ref<Record<string,string>>({}),editing=ref<ConnectionProvider|null>(null),deleting=ref<string|null>(null)
const editingRow=ref<Connection|null>(null)
const deleteTarget=ref<Connection|null>(null)
watch(deleting,id=>{deleteTarget.value=rows.value.find(row=>row.id===id)??null},{flush:'sync'})
watch(rows,current=>{
  const target=deleteTarget.value
  if(target&&!current.some(row=>row.id===target.id&&row.revision===target.revision))deleting.value=null
},{flush:'sync'})
let controller:AbortController|null=null,epoch=0,createId=crypto.randomUUID()
const errors:Record<number,string>={401:"Войдите в панель заново",403:"Управление подключениями доступно оператору проекта",404:"Подключение не найдено",409:"Запись уже существует. Обновите список",422:"Проверьте параметры сервиса и доступность учётной записи"}
async function request(data:Record<string,unknown>):Promise<Record<string,unknown>|null>{
  if(!ready.value||busy.value)return null
  busy.value=true;message.value=""
  const run=epoch,abort=new AbortController();controller=abort
  const timeout=setTimeout(()=>abort.abort(),18000)
  try{
    const response=await fetch("/api/v1/connections",{method:"POST",credentials:"same-origin",cache:"no-store",
      headers:{"Content-Type":"application/json"},body:JSON.stringify({...data,project_uuid:props.selectedProjectId}),signal:abort.signal})
    const result=await readBoundedJsonResponse(response,abort.signal,131072,true)
    if(run!==epoch||abort.signal.aborted)return null
    if(!response.ok){message.value=errors[response.status]??"Сервис подключений недоступен. Обновите список перед повтором";return null}
    if(!result||typeof result!=="object"||Array.isArray(result))throw new Error("Invalid response")
    return result as Record<string,unknown>
  }catch{if(run===epoch)message.value="Ответ не получен. Обновите список, чтобы уточнить результат";return null}
  finally{clearTimeout(timeout);if(run===epoch){busy.value=false;controller=null}}
}
async function reload(){
  const all:Connection[]=[];let cursor:string|undefined
  do{
  const result=await request({action:"list",...(cursor?{cursor}:{})})
  if(!result)return
  if(!Array.isArray(result.items)||result.items.length>50||result.items.some((r:unknown)=>{
    if(!r||typeof r!=="object")return true
    const row=r as Record<string,unknown>
    return typeof row.id!=="string"||typeof row.name!=="string"||typeof row.base_url!=="string"||!Number.isSafeInteger(row.revision)||!row.configuration||typeof row.configuration!=="object"||!(String(row.provider) in connectionProviders)
  })){message.value="Сервис вернул некорректный список";return}
  all.push(...result.items as Connection[])
  if(result.has_more!==true)break
  if(typeof result.next_cursor!=="string"||result.next_cursor===cursor){message.value="Некорректная страница подключений";return}
  cursor=result.next_cursor
  }while(cursor)
  rows.value=all
}
async function load(){
  const schema=await request({action:"forms"})
  schemaReady.value=!!schema&&typeof schema.$defs==="object"&&schema.$defs!==null
  if(schemaReady.value)await reload()
}
function open(provider:ConnectionProvider,row:Connection|null=null){message.value="";createId=crypto.randomUUID();editingRow.value=row;editing.value=provider}
async function submit(action:"verify"|"create",configuration:Record<string,unknown>,credential:string){
  const result=await request({action:action==="create"&&editingRow.value?"update":action,configuration,credential,
    connection_uuid:editingRow.value?.id??createId,expected_revision:editingRow.value?.revision??null,
    alias:`${String(configuration.provider)}-${createId.slice(0,8)}`})
  if(result?.status&&result.status!=="connected")message.value=result.status==="denied"?"Провайдер отклонил учётные данные или доступ":"Не удалось подтвердить подключение к сервису"
  return result
}
async function saved(){editing.value=null;await reload()}
async function check(row:Connection){
  const result=await request({action:"check",connection_uuid:row.id})
  if(result)checks.value[row.id]=result.status==="connected"?`Подключено${typeof result.identity==="string"?` · ${result.identity}`:""}`:
    result.status==="denied"?"Доступ отклонён":"Подключение не подтверждено"
}
async function remove(row:Connection){
  const result=await request({action:"delete",connection_uuid:row.id,expected_revision:row.revision})
  if(result){deleting.value=null;delete checks.value[row.id];await reload()}
}
watch(()=>JSON.stringify([props.context.user.id,props.selectedProjectId,ready.value]),()=>{
  ++epoch;controller?.abort();busy.value=false;rows.value=[];checks.value={};editing.value=null;deleting.value=null;schemaReady.value=false

},{immediate:true})
const liveQuery=useLiveQuery(load,{enabled:()=>ready.value,paused:()=>busy.value,topics:['management.events'],accept:event=>event.type.startsWith('connection.')&&(event.data as Record<string,unknown>|null)?.project_id===props.selectedProjectId})
watch(()=>props.selectedProjectId,()=>liveQuery.invalidate())
onBeforeUnmount(()=>{++epoch;controller?.abort()})
</script>

<template>
  <div class="space-y-5">
    <div v-if="!embedded" class="flex flex-wrap items-start justify-between gap-3">
      <div><h2 class="text-2xl font-semibold tracking-tight">Подключения</h2><p class="mt-1 text-sm text-muted-foreground">Учётные записи сервисов выбранного проекта</p></div>

    </div>
    <Tabs v-model="section"><TabsList><TabsTrigger value="vcs">Системы контроля версий</TabsTrigger><TabsTrigger value="infrastructure">Инфраструктура</TabsTrigger></TabsList></Tabs>
    <Tabs v-model="selectedProvider"><TabsList><TabsTrigger v-for="provider in providers" :key="provider" :value="provider">{{connectionProviders[provider].title}}</TabsTrigger></TabsList></Tabs>
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div><h3 class="text-xl font-semibold tracking-tight">{{connectionProviders[selectedProvider].title}}</h3><p class="mt-1 text-sm text-muted-foreground">{{connectionProviders[selectedProvider].description}}</p></div>
      <div class="flex items-center gap-2">
        <Button size="sm" :disabled="busy||!ready||!schemaReady" @click="open(selectedProvider)"><Plus class="mr-2 size-4"/>Добавить аккаунт</Button>
      </div>
    </div>
    <p v-if="context.user.role!=='operator'" class="rounded-lg border p-4 text-sm text-muted-foreground">Подключениями управляет оператор проекта.</p>
    <p v-if="message&&!editing" role="status" class="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">{{message}}</p>
    <div class="overflow-hidden rounded-lg border">
      <Table>
        <TableHeader><TableRow><TableHead>Название</TableHead><TableHead>Авторизация</TableHead><TableHead>Адрес сервиса</TableHead><TableHead class="text-right">Действия</TableHead></TableRow></TableHeader>
        <TableBody v-if="live">
          <TableRow v-for="row in displayed" :key="row.id">
            <TableCell class="font-medium">{{row.name}}<Badge v-if="checks[row.id]" variant="outline" class="ml-2">{{checks[row.id]}}</Badge></TableCell>
            <TableCell class="text-xs">{{authLabel(row.auth_type)}}</TableCell><TableCell class="text-xs text-muted-foreground">{{row.base_url}}</TableCell>
            <TableCell><div class="flex justify-end gap-1"><Button size="icon" variant="ghost" class="size-8" :disabled="busy||!ready" :aria-label="`Проверить ${row.name}`" @click="check(row)"><PlugZap class="size-4"/></Button><Button size="icon" variant="ghost" class="size-8" :disabled="busy||!ready" :aria-label="`Изменить ${row.name}`" @click="open(row.provider,row)"><Pencil class="size-4"/></Button><Button size="icon" variant="ghost" class="size-8" :disabled="busy||!ready" :aria-label="`Удалить ${row.name}`" @click="deleting=row.id"><Trash2 class="size-4"/></Button></div>
            </TableCell>
          </TableRow>
          <TableRow v-if="!displayed.length"><TableCell :colspan="4" class="h-28 text-center text-muted-foreground">{{busy?'Загружаем аккаунты…':'Аккаунты ещё не подключены'}}</TableCell></TableRow>
        </TableBody>
      </Table>
    </div>
    <ConfirmationDialog :open="!!deleteTarget" title="Удалить подключение?" :description="`Подключение ${deleteTarget?.name||''} будет удалено из проекта.`" confirm-label="Удалить" :busy="busy" @update:open="value=>{if(!value)deleting=null}" @confirm="deleteTarget&&remove(deleteTarget)"/>
    <BaseConnectionForm v-if="editing&&ready" :key="editingRow?.id??editing" :provider="editing" :initial="editingRow?.configuration" :busy="busy" :message="message" :submit="submit" @close="editing=null" @saved="saved"/>
  </div>
</template>
