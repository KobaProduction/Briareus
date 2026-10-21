<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from 'vue'
import {X,Plus,ArrowLeft,RotateCw,RotateCcw,Settings,Puzzle,ArrowRight,LockKeyhole,LockKeyholeOpen} from 'lucide-vue-next'
import {eventBus} from '@/shared/events/bus'
import {useLiveQuery} from '@/shared/lib/use-live-query'
import SessionPicker from '@/features/agent-sessions/ui/SessionPicker.vue'
import {listCurrentSessions,type CurrentAgentSession} from '@/features/agent-sessions'
import {requestSessionElevation} from '@/features/approvals'
import type {VerifiedPlatformContext} from '@/entities/workspace/model/proof'
import {parseHandEffectScopes,type HandEffectScope} from '@/shared/lib/hand-effect-scope'
import {browserValue,transportLabel,reconcileSelection,editableBrowserElement,mergeBrowserInputs,type BrowserTab,type BrowserElement} from '@/features/browser/model/browser-state'
import {Button} from '@/shared/ui/button'
import {Input} from '@/shared/ui/input'
import RowActions from '@/shared/ui/RowActions.vue'
import {Select,SelectTrigger,SelectValue,SelectContent,SelectItem} from '@/shared/ui/select'
import {Card,CardContent,CardHeader,CardTitle} from '@/shared/ui/card'
const props=defineProps<{context:VerifiedPlatformContext;selectedProjectId:string|null}>()
const emit=defineEmits<{selectProject:[id:string];openSessions:[]}>()
const project=computed(()=>props.context.projects.find(p=>p.id===props.selectedProjectId))
const identityKey=computed(()=>JSON.stringify([props.context.rauthy.issuer,props.context.rauthy.subject,props.context.user.id,props.selectedProjectId]))
const scopes=ref<HandEffectScope[]>([]),sessions=ref<CurrentAgentSession[]>([]),sessionId=ref('')
const tabs=ref<BrowserTab[]>([]),tabId=ref(''),draft=ref('https://example.com'),notice=ref(''),busy=ref(false),pending=ref(false)
const canReopen=ref(false)
const snapshot=ref<any>(null),preview=ref(''),zoom=ref(100),width=ref(1280),height=ref(720),inputValues=ref<Record<string,string>>({})
const current=computed(()=>tabs.value.find(tab=>tab.page_id===tabId.value))
const chosen=computed(()=>sessions.value.find(session=>session.session_uuid===sessionId.value))
const allowed=computed(()=>!!chosen.value&&scopes.value.length>0&&scopes.value.every(scope=>chosen.value!.resources.some(grant=>
  grant.hand===scope.hand&&grant.tool===scope.tool&&grant.action===scope.action&&grant.resource.kind===scope.resource.kind&&grant.resource.id===scope.resource.id)))
let generation=0,controller=new AbortController()
const elements=computed<BrowserElement[]>(()=>Array.isArray(snapshot.value?.elements)?snapshot.value.elements:[])
function fail(error:unknown){notice.value=error instanceof Error?error.message:'Браузер недоступен'}
async function rpc(tool:string,args:Record<string,unknown>={},requestId=crypto.randomUUID()){
  if(!project.value||!chosen.value)throw new Error('Выберите проект и действующий сеанс')
  const raw=await eventBus.request<any>('browser.command',{project_uuid:project.value.id,agent_session_uuid:chosen.value.session_uuid,
    expected_grant_revision:chosen.value.revision,operation_uuid:requestId,tool,arguments:args},controller.signal)
  return browserValue(raw)
}
async function effect(tool:string,args:Record<string,unknown>={}){
  const run=generation
  const requestId=crypto.randomUUID();let op
  try{op=await rpc('web_operation_start',{tool,arguments:args},requestId)}catch(startError){
    if(run!==generation)throw startError
    op=await rpc('web_operation_poll',{operation_id:'request:'+requestId,tool})
  }
  while(op.state==='running'){
    await new Promise(resolve=>setTimeout(resolve,1500))
    if(run!==generation)throw new Error('Рабочая область изменена')
    op=await rpc('web_operation_poll',{operation_id:op.operation_id,tool})
  }
  if(run!==generation)throw new Error('Рабочая область изменена')
  if(op.state!=='completed')throw new Error('Операция браузера не выполнена: '+op.state)
  return browserValue(op.result)
}
async function inventory(){
  const result=await effect('local_browser_pages')
  if(!Array.isArray(result.pages))throw new Error('Некорректный список вкладок')
  tabs.value=result.pages.filter((tab:any)=>typeof tab.page_id==='string'&&typeof tab.url==='string')
  canReopen.value=result.can_reopen_closed_tab===true
  const next=reconcileSelection(tabs.value,tabId.value)
  if(next!==tabId.value){tabId.value=next;draft.value=tabs.value.find(tab=>tab.page_id===next)?.url??'https://example.com';snapshot.value=null;preview.value=''}
}
async function load(){
  if(!project.value||busy.value)return
  const run=generation
  try{
    const response=await eventBus.request<{items:unknown}>('browser.resources',{project_uuid:project.value.id},controller.signal)
    const found=parseHandEffectScopes(response.items,['web.access'],project.value.id)
    if(!found?.length)throw new Error('Браузер проекта не подключён')
    const result=await listCurrentSessions(project.value.id,props.context.user.id,project.value.permissions.includes('approve_agent_session'),controller.signal)
    if(run!==generation)return
    if(result.kind!=='ready')throw new Error(result.code)
    scopes.value=found;sessions.value=result.items.filter(item=>item.created_by_user_uuid===props.context.user.id&&item.status==='active'&&Date.parse(item.hard_expires_at)>Date.now())
    if(!sessions.value.some(item=>item.session_uuid===sessionId.value))sessionId.value=sessions.value[0]?.session_uuid??''
    if(allowed.value)await act(async()=>{const status=await rpc('local_browser_status');if(status.running===false){notice.value='Браузер подготавливается…';return}await inventory()})
  }catch(error){if(run===generation)fail(error)}
}
async function act(work:()=>Promise<void>){if(busy.value)return;const run=generation;busy.value=true;notice.value='';try{await work()}catch(error){if(run===generation)fail(error)}finally{if(run===generation)busy.value=false}}
async function readPage(id:string){
  preview.value=''
  const value=await effect('local_browser_snapshot',{page_id:id})
  if(tabId.value===id){inputValues.value=mergeBrowserInputs(elements.value,value.elements??[],inputValues.value,snapshot.value?.page_id===id&&snapshot.value?.url===value.url);snapshot.value=value}
  const image=await effect('local_browser_preview',{page_id:id})
  if(tabId.value===id){
    snapshot.value=value;preview.value=''
    if(image.page_id===id&&image.mime_type==='image/png'&&typeof image.data_base64==='string'&&image.data_base64.length<=1400000&&/^[A-Za-z0-9+/]+=*$/.test(image.data_base64))preview.value='data:image/png;base64,'+image.data_base64
  }
}
function selectTab(id:string){if(busy.value)return;tabId.value=id;draft.value=current.value?.url??'';snapshot.value=null;preview.value='';void act(()=>readPage(id))}
function navigate(newTab=false){const address=draft.value.trim();try{const parsed=new URL(address);if(!['http:','https:'].includes(parsed.protocol))throw 0}catch{notice.value='Введите полный HTTP или HTTPS адрес';return}
  const selected=newTab?'':tabId.value
  void act(async()=>{const result=await effect('local_browser_open',{url:address,page_id:selected});await inventory();tabId.value=result.page_id;
    if(draft.value.trim()===address)draft.value=result.url;await readPage(result.page_id)})}
function closeTab(id:string){const wasActive=tabId.value===id;void act(async()=>{await effect('local_browser_close_page',{page_id:id});await inventory();if(wasActive&&tabId.value)await readPage(tabId.value)})}
function browserMenu(action:'restore'|'settings'|'extensions'){
  if(!allowed.value||busy.value||action==='restore'&&!canReopen.value)return
  void act(async()=>{
    const result=await effect(action==='restore'?'local_browser_reopen_closed_page':'local_browser_settings',action==='restore'?{}:{section:action})
    await inventory();tabId.value=result.page_id;draft.value=result.url;await readPage(result.page_id)
  })
}
function browserShortcut(event:KeyboardEvent){
  if((event.ctrlKey||event.metaKey)&&event.shiftKey&&event.key.toLowerCase()==='t'){
    event.preventDefault();browserMenu('restore')
  }
}
function pageAction(tool:string){const id=tabId.value;void act(async()=>{await effect(tool,{page_id:id});await inventory();if(tabId.value===id){draft.value=current.value?.url??draft.value;await readPage(id)}})}
function resize(){if(!Number.isInteger(width.value)||!Number.isInteger(height.value)||width.value<320||height.value<240||width.value>7680||height.value>4320){notice.value='Viewport: ширина 320–7680, высота 240–4320';return}
  const id=tabId.value;void act(async()=>{const result=await effect('local_browser_set_viewport',{page_id:id,width:width.value,height:height.value});width.value=result.viewport?.width??width.value;height.value=result.viewport?.height??height.value;await readPage(id)})}
function interact(element:BrowserElement){const id=tabId.value;void act(async()=>{
  const editable=editableBrowserElement(element)
  try{await effect(editable?'local_browser_fill':'local_browser_click',{page_id:id,ref:element.ref,...(editable?{value:inputValues.value[element.ref]??''}:{})})}
  finally{if((element.type??'').toLowerCase()==='password')delete inputValues.value[element.ref]}
  await inventory();await readPage(id)
})}
async function requestAccess(){if(!chosen.value)return;await act(async()=>{const result=await requestSessionElevation(chosen.value!,scopes.value,300,props.context.user.id,controller.signal);pending.value=result.kind==='pending'||result.kind==='uncertain';notice.value=pending.value?'Запрос отправлен. Подтвердите его в согласованиях.':'Не удалось запросить доступ'})}
watch(identityKey,()=>{generation++;controller.abort();controller=new AbortController();busy.value=false;pending.value=false;scopes.value=[];sessions.value=[];tabs.value=[];canReopen.value=false;tabId.value='';snapshot.value=null;preview.value='';sessionId.value='';notice.value=''},{immediate:true})
const live=useLiveQuery(load,{enabled:()=>!!project.value,paused:()=>busy.value,topics:['access.sessions','management.events','browser.runtime']})
watch(identityKey,()=>live.invalidate())
watch(sessionId,()=>{tabs.value=[];canReopen.value=false;tabId.value='';snapshot.value=null;preview.value='';if(allowed.value)void load()})
onBeforeUnmount(()=>{generation++;controller.abort()})
</script>
<template>
<Card @keydown="browserShortcut"><CardHeader class="flex flex-row flex-wrap items-center justify-between gap-2"><CardTitle>Браузер проекта</CardTitle><Button variant="outline" @click="emit('openSessions')">Сеансы и согласования</Button></CardHeader>
<CardContent class="min-w-0 space-y-3">
<label class="block max-w-lg text-sm">Сеанс выполнения<SessionPicker v-model="sessionId" :items="sessions" :disabled="busy"/></label>
<Button v-if="chosen&&!allowed&&scopes.length" :disabled="busy||pending" @click="requestAccess">Запросить доступ</Button>
<div role="tablist" aria-label="Вкладки браузера" class="flex min-w-0 gap-1 overflow-x-auto border-b pb-1">
<div v-for="tab in tabs" :key="tab.page_id" class="flex shrink-0 items-center rounded-t bg-muted/40" :class="{'bg-muted':tabId===tab.page_id}">
<button role="tab" :aria-selected="tabId===tab.page_id" :disabled="busy" class="max-w-48 truncate px-3 py-2 text-sm" :title="tab.url+' · '+tab.page_id" @click="selectTab(tab.page_id)">{{tab.label||tab.title||'Новая вкладка'}}</button>
<Button size="icon" variant="ghost" class="h-7 w-7" :disabled="busy||!allowed" :aria-label="'Закрыть вкладку '+(tab.title||tab.page_id)" @click.stop="closeTab(tab.page_id)"><X class="h-3 w-3"/></Button></div>
<Button size="icon" variant="ghost" :disabled="busy||!allowed" aria-label="Открыть адрес в новой вкладке" @click="navigate(true)"><Plus class="h-4 w-4"/></Button></div>
<form class="flex items-center gap-1" @submit.prevent="navigate(false)"><Button type="button" size="icon" variant="ghost" :disabled="busy||!allowed||!tabId" aria-label="Назад" @click="pageAction('local_browser_back')"><ArrowLeft class="h-4 w-4"/></Button>
<Button type="button" size="icon" variant="ghost" :disabled="busy||!allowed||!tabId" aria-label="Вперёд" @click="pageAction('local_browser_forward')"><ArrowRight class="h-4 w-4"/></Button>
<Button type="button" size="icon" variant="ghost" :disabled="busy||!allowed||!tabId" aria-label="Перезагрузить страницу" @click="pageAction('local_browser_reload')"><RotateCw class="h-4 w-4"/></Button>
<component :is="current?.url.startsWith('https:')?LockKeyhole:LockKeyholeOpen" class="h-4 w-4 shrink-0" :title="transportLabel(current?.url??'')"/>
<Input v-model="draft" class="min-w-0 flex-1" aria-label="Адрес страницы" placeholder="https://example.com"/><Button :disabled="busy||!allowed" type="submit">{{busy?'Выполняется…':'Перейти'}}</Button>
<RowActions label="Меню браузера" :disabled="busy">
<Button type="button" variant="ghost" class="h-auto w-full justify-start whitespace-normal text-left" :disabled="!allowed||!canReopen" @click="browserMenu('restore')"><RotateCcw class="size-4 shrink-0"/><span>Восстановить закрытую вкладку<span class="block text-xs text-muted-foreground">Ctrl+Shift+T</span></span></Button>
<Button type="button" variant="ghost" class="w-full justify-start" :disabled="!allowed" @click="browserMenu('settings')"><Settings class="size-4"/>Настройки Chromium</Button>
<Button type="button" variant="ghost" class="w-full justify-start" :disabled="!allowed" @click="browserMenu('extensions')"><Puzzle class="size-4"/>Расширения</Button>
</RowActions></form>
<p class="text-xs text-muted-foreground">{{transportLabel(current?.url??'')}}<span v-if="current"> · {{current.page_id}}</span></p>
<div class="flex flex-wrap items-end gap-2"><label class="text-xs">Ширина<Input v-model.number="width" type="number" class="w-24" min="320" max="7680"/></label><label class="text-xs">Высота<Input v-model.number="height" type="number" class="w-24" min="240" max="4320"/></label><Button variant="outline" :disabled="busy||!allowed||!tabId" @click="resize">Viewport</Button>
<label class="ml-auto text-xs">Масштаб просмотра<Select :model-value="String(zoom)" @update:model-value="value=>zoom=Number(value)"><SelectTrigger class="mt-1 w-28" aria-label="Масштаб просмотра"><SelectValue/></SelectTrigger><SelectContent><SelectItem v-for="value in [50,75,100,125,150,200]" :key="value" :value="String(value)">{{value}}%</SelectItem></SelectContent></Select></label></div>
<p v-if="notice" role="status" class="break-words text-sm">{{notice}}</p>
<div v-if="preview" class="max-h-[70vh] overflow-auto rounded border bg-white"><img :src="preview" alt="Снимок выбранной вкладки" class="max-w-none" :style="{width:width*zoom/100+'px'}"/></div>
<section v-if="snapshot" role="tabpanel" aria-label="Содержимое выбранной вкладки" class="space-y-3 overflow-auto rounded border p-3" :style="{fontSize:zoom/100+'rem'}"><h3 class="font-medium">{{snapshot.title}}</h3><pre class="whitespace-pre-wrap break-words font-sans">{{snapshot.text}}</pre>
<p v-if="snapshot.text_truncated" class="text-sm text-muted-foreground">Содержимое сокращено браузером.</p>
<div v-if="elements.length" class="space-y-2 border-t pt-3"><p class="text-sm font-medium">Элементы страницы</p><div v-for="element in elements" :key="element.ref" class="flex flex-wrap items-center gap-2"><label class="min-w-0 flex-1 break-words text-sm">{{element.name||element.text||element.role||element.tag||element.ref}}<Input v-if="editableBrowserElement(element)" v-model="inputValues[element.ref]" :type="element.type==='password'?'password':'text'" :disabled="busy||element.disabled"/></label><Button variant="outline" :disabled="busy||element.disabled||element.type==='file'||(editableBrowserElement(element)&&inputValues[element.ref]===(element.value??''))" @click="interact(element)">{{editableBrowserElement(element)?'Ввести':'Нажать'}}</Button></div></div>
</section><p v-else-if="!busy" class="text-sm text-muted-foreground">{{tabs.length?'Выберите вкладку, чтобы открыть её содержимое.':'Откройте HTTP или HTTPS адрес. Вкладки принадлежат выбранному проекту и сеансу.'}}</p>
</CardContent></Card>
</template>
