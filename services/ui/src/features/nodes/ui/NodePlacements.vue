<script setup lang="ts">
import {computed,onScopeDispose,ref,watch} from 'vue'
import type {ManagedNode,ResourceLimits} from '@/entities/node/model/types'
import type {ModuleCatalog} from '@/entities/node/model/modules'
import {nodeCommand} from '../api/nodes'
import RuntimePolicySettings from './RuntimePolicySettings.vue'
import type {ModuleConfiguration} from '../model/module-configuration'
import {configurationValid,defaultConfiguration,initialConfiguration} from '../model/module-configuration'
import {moduleName,moduleLabel} from '../model/module-presentation'
import PlacementConfiguration from './PlacementConfiguration.vue'
import ProjectWorkspaceSelector from './ProjectWorkspaceSelector.vue'
import type {ProjectWorkspace,ProjectWorkspaceMount} from '../model/project-workspace'
import {projectWorkspaceField} from '../model/project-workspace'
import {currentPlacementRelease,placementConfigurationField,placementHasChanges} from '../model/placement-edit'
import {useLiveQuery} from '@/shared/lib/use-live-query'
import DataTable from '@/shared/ui/data-table/DataTable.vue'
import EditorDialog from '@/shared/ui/EditorDialog.vue'
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription} from '@/shared/ui/dialog'
import {Button} from '@/shared/ui/button'
import {Input} from '@/shared/ui/input'
import StatusBadge from '@/shared/ui/StatusBadge.vue'
import PlacementOperation from './PlacementOperation.vue'
import PlacementStatusDetails from './PlacementStatusDetails.vue'
import {placementStatus,operationInProgress,type PlacementOperation as PlacementOperationData} from '../model/operation-presentation'
import {Select,SelectContent,SelectGroup,SelectLabel,SelectItem,SelectTrigger,SelectValue} from '@/shared/ui/select'

interface Placement {runtime_policy_pending?:boolean;id:string;name:string;module:string;state:string;sequence:number;release_uuid:string;limits:ResourceLimits;workspace_uuid:string|null;configuration?:ModuleConfiguration|null;project_workspace?:ProjectWorkspaceMount|null;operation:PlacementOperationData|null}
const props=defineProps<{node:ManagedNode;projectId:string}>()
const emit=defineEmits<{close:[]}>()
const rows=ref<Placement[]>([]),catalog=ref<ModuleCatalog>({modules:[],artifacts:[],releases:[]})
const loading=ref(false),busy=ref(false),error=ref(''),formError=ref(''),editor=ref(false),recovering=ref<string|null>(null)
const name=ref('Файлы проекта'),release=ref(''),memory=ref('128'),cpu=ref('100'),pids=ref('32')
const updating=ref<Placement|null>(null)
const configuration=ref<ModuleConfiguration>({})
const workspaces=ref<ProjectWorkspace[]>([]),projectWorkspace=ref<ProjectWorkspaceMount|null>(null),workspaceBusy=ref(false),workspaceError=ref('')
let workspaceOperation=crypto.randomUUID()
let disposed=false,operation=crypto.randomUUID(),placementId=crypto.randomUUID(),submittedIntent:string|null=null
onScopeDispose(()=>{disposed=true})
async function read(){
 loading.value=true
 try{
  const results=await Promise.all([
   nodeCommand<{items:Placement[]}>(props.projectId,{operation_uuid:crypto.randomUUID(),action:'modules',module:{action:'placements',node_uuid:props.node.id}}),
   nodeCommand<ModuleCatalog>(props.projectId,{operation_uuid:crypto.randomUUID(),action:'modules',module:{action:'catalog'}})])
  if(!disposed){rows.value=results[0].items;catalog.value=results[1];error.value=''}
  await readWorkspaces()
 }catch{if(!disposed)error.value='Не удалось получить MCP выбранного проекта на ноде.'}
 finally{if(!disposed)loading.value=false}
}
function verifiedWorkspace(item:ProjectWorkspace){return item&&item.node_uuid===props.node.id&&item.project_uuid===props.projectId&&item.purpose==='workspace'&&item.retention==='persistent'&&typeof item.id==='string'&&/^[a-f0-9-]{36}$/i.test(item.id)}
async function readWorkspaces(){
 workspaceBusy.value=true
 try{
  const result=await nodeCommand<{items:ProjectWorkspace[]}>(props.projectId,{operation_uuid:crypto.randomUUID(),action:'modules',module:{action:'workspaces',node_uuid:props.node.id}})
  if(!Array.isArray(result.items)||result.items.length>1||!result.items.every(verifiedWorkspace))throw new Error('WORKSPACE_INVALID')
  if(!disposed){workspaces.value=result.items;workspaceError.value=''}
 }catch{if(!disposed)workspaceError.value='Не удалось получить рабочую папку проекта.'}
 finally{if(!disposed)workspaceBusy.value=false}
}
async function ensureWorkspace(){
 if(workspaceBusy.value||busy.value)return
 workspaceBusy.value=true;workspaceError.value=''
 try{
  const result=await nodeCommand<{item:ProjectWorkspace}>(props.projectId,{operation_uuid:workspaceOperation,action:'modules',module:{action:'ensure_workspace',node_uuid:props.node.id}})
  if(!verifiedWorkspace(result.item))throw new Error('WORKSPACE_INVALID')
  if(!disposed){workspaces.value=[result.item];projectWorkspace.value={id:result.item.id,read_only:false};workspaceOperation=crypto.randomUUID()}
 }catch{if(!disposed)workspaceError.value='Создание папки не подтверждено. Повтор использует ту же операцию.'}
 finally{if(!disposed)workspaceBusy.value=false}
}
const live=useLiveQuery(read,{enabled:()=>!!props.projectId,topics:['management.events'],accept:event=>event.type==='node.modules'||event.type==='node.runtime_policy'||event.type.startsWith('node.module.')})
const releases=computed(()=>catalog.value.releases.filter(row=>catalog.value.modules.some(module=>module.components.includes(row.module))&&catalog.value.artifacts.some(item=>item.key===row.module&&item.node_adapter)&&
 (!updating.value||row.module===updating.value.module)))
const artifact=computed(()=>catalog.value.artifacts.find(item=>item.key===releases.value.find(row=>row.id===release.value)?.module))
const selectedModule=computed(()=>artifact.value?.key??updating.value?.module??'')
const releaseSections=computed(()=>catalog.value.modules.map(section=>({id:section.key,name:section.name,releases:releases.value.filter(row=>section.components.includes(row.module))})).filter(section=>section.releases.length))
watch(selectedModule,module=>{if(!updating.value){configuration.value=defaultConfiguration(module);projectWorkspace.value=null}})
function applyReleaseDefaults(){
 if(!artifact.value)return
 if(updating.value){
  const minimum=artifact.value.minimum_limits
  memory.value=String(Math.max(Number(memory.value),minimum.memory_bytes/1024**2))
  cpu.value=String(Math.max(Number(cpu.value),minimum.cpu_millis));pids.value=String(Math.max(Number(pids.value),minimum.pids))
 }else if(artifact.value.default_limits){
  const limits=artifact.value.default_limits;memory.value=String(limits.memory_bytes/1024**2);cpu.value=String(limits.cpu_millis);pids.value=String(limits.pids)
  if(!name.value.trim())name.value=artifact.value.name
 }
}
watch(release,applyReleaseDefaults)
const valid=computed(()=>!!name.value.trim()&&releases.value.some(item=>item.id===release.value)&&
 (!['web','reverse'].includes(selectedModule.value)||!workspaceBusy.value)&&
 Number.isInteger(Number(memory.value))&&Number(memory.value)>=(artifact.value?.minimum_limits?.memory_bytes??64*1024**2)/1024**2&&Number(memory.value)<=props.node.budget.total.memory_bytes/1024**2&&
 Number.isInteger(Number(cpu.value))&&Number(cpu.value)>=(artifact.value?.minimum_limits?.cpu_millis??100)&&Number(cpu.value)<=props.node.budget.total.cpu_millis&&
 configurationValid(selectedModule.value,configuration.value)&&
 Number.isInteger(Number(pids.value))&&Number(pids.value)>=(artifact.value?.minimum_limits?.pids??32)&&Number(pids.value)<=props.node.budget.total.pids)
const editLimits=computed(()=>({memory_bytes:Number(memory.value)*1024**2,cpu_millis:Number(cpu.value),pids:Number(pids.value)}))
const changed=computed(()=>!updating.value||updating.value.runtime_policy_pending||placementHasChanges(updating.value,release.value,releases.value,editLimits.value,configuration.value,projectWorkspace.value))
function open(){submittedIntent=null;updating.value=null;projectWorkspace.value=null;name.value='';operation=crypto.randomUUID();placementId=crypto.randomUUID();release.value=releases.value[0]?.id??'';configuration.value=defaultConfiguration(releases.value.find(row=>row.id===release.value)?.module??'');applyReleaseDefaults();formError.value='';editor.value=true}
function openUpdate(row:Placement){if(busy.value||operationInProgress(row.operation)||row.operation?.reconciliation_required)return;submittedIntent=null;updating.value=row;projectWorkspace.value=row.project_workspace?{...row.project_workspace}:null;operation=crypto.randomUUID();name.value=row.name;memory.value=String(row.limits.memory_bytes/1024**2);cpu.value=String(row.limits.cpu_millis);pids.value=String(row.limits.pids);release.value=currentPlacementRelease(row.release_uuid,releases.value);configuration.value=initialConfiguration(row.module,row.configuration);applyReleaseDefaults();formError.value='';editor.value=true}
async function place(){
 if(busy.value||!valid.value||!changed.value)return
 busy.value=true;formError.value=''
 try{
  const configurable=updating.value?placementConfigurationField(selectedModule.value,updating.value.configuration,configuration.value):
   ['web','serena'].includes(selectedModule.value)?{configuration:configuration.value}:{}
  const workspace=projectWorkspaceField(selectedModule.value,updating.value?.project_workspace,projectWorkspace.value,!!updating.value)
  const limits=editLimits.value
  const module=updating.value?{action:'update',update:{id:updating.value.id,release_uuid:release.value,expected_sequence:updating.value.sequence,limits,...configurable,...workspace}}:
   {action:'place',placement:{id:placementId,node_uuid:props.node.id,release_uuid:release.value,name:name.value.trim(),limits,...configurable,...workspace}}
  const intent=JSON.stringify(module)
  if(submittedIntent!==null&&submittedIntent!==intent)operation=crypto.randomUUID()
  submittedIntent=intent
  await nodeCommand(props.projectId,{operation_uuid:operation,action:'modules',module})
  editor.value=false;live.invalidate()
 }catch{formError.value='Запуск не подтверждён. Проверьте список операций: повтор сохранит идентификатор и не создаст второе размещение.'}
 finally{busy.value=false}
}
const recoveryIntents=new Map<string,{id:string;sequence:number}>()
const recoveryKey=(id:string)=>'briareus-placement-recovery:'+props.projectId+':'+props.node.id+':'+id
async function recover(row:Placement){
 if(busy.value||!props.node.enabled||operationInProgress(row.operation)||row.operation?.reconciliation_required)return
 let intent=recoveryIntents.get(row.id)
 if(!intent){try{const saved=JSON.parse(sessionStorage.getItem(recoveryKey(row.id))||'null');if(saved&&/^[0-9a-f-]{36}$/.test(saved.id)&&Number.isSafeInteger(saved.sequence)&&saved.sequence>0)intent=saved}catch{/* Server independently validates recovery authority. */}}
 if(!intent){intent={id:crypto.randomUUID(),sequence:row.sequence};recoveryIntents.set(row.id,intent);try{sessionStorage.setItem(recoveryKey(row.id),JSON.stringify(intent))}catch{/* In-memory exact retry remains available. */}}
 busy.value=true;recovering.value=row.id;error.value=''
 try{
  await nodeCommand(props.projectId,{operation_uuid:intent.id,action:'modules',module:{action:'recover',recover:{id:row.id,expected_sequence:intent.sequence}}})
  recoveryIntents.delete(row.id);try{sessionStorage.removeItem(recoveryKey(row.id))}catch{/* Optional browser recovery storage. */}live.invalidate()
 }catch{error.value='Запуск сохранённой конфигурации не подтверждён. Повтор использует ту же операцию; сборка и параметры не меняются.';live.invalidate()}
 finally{busy.value=false;recovering.value=null}
}
async function reconcile(row:Placement){
 if(!row.operation?.reconciliation_required||busy.value)return
 busy.value=true;recovering.value=row.id
 try{await nodeCommand(props.projectId,{operation_uuid:crypto.randomUUID(),action:'modules',module:{action:'reconcile',target_operation_uuid:row.operation.id}});live.invalidate()}
 catch{error.value='Сверка с журналом ноды не подтверждена.'}
 finally{busy.value=false;recovering.value=null}
}
</script>
<template>
 <Dialog :open="true" @update:open="value=>{if(!value&&!busy)emit('close')}"><DialogContent class="min-w-0 w-[calc(100vw-2rem)] max-w-[calc(100vw-2rem)] max-h-[90vh] overflow-y-auto sm:max-w-4xl [&>*]:min-w-0 [&>*]:max-w-full"><DialogHeader class="min-w-0 max-w-full"><DialogTitle>MCP: {{node.name}}</DialogTitle><RuntimePolicySettings :project-id="projectId" :node-id="node.id"/><DialogDescription class="whitespace-normal break-words">Рабочая папка проекта общая для MCP этой ноды. Профили браузера и данные инфраструктуры хранятся отдельно.</DialogDescription></DialogHeader>
 <div class="flex justify-end"><Button :disabled="!node.enabled||busy||!releases.length" @click="open">Добавить MCP</Button></div>
 <p v-if="error" role="alert" class="text-sm text-destructive">{{error}}</p>
 <p v-if="!loading&&!rows.length" class="text-sm text-muted-foreground">В этом проекте на ноде ещё нет размещённых MCP.</p>
 <DataTable class="min-w-0 max-w-full" :rows="rows" :loading="loading" label="MCP ноды" :search-text="row=>row.name+' '+moduleLabel(row.module,catalog.artifacts.find(item=>item.key===row.module)?.name??row.module)" :columns="[{key:'name',title:'Название',dataIndex:'name'},{key:'moduleName',title:'Модуль',dataIndex:'module',defaultHidden:true},{key:'state',title:'Состояние'},{key:'limits',title:'Лимиты'},{key:'actions',title:'Операция'}]">
 <template #cell="{row,column}">
  <div v-if="column.key==='name'" class="min-w-0 max-w-36 [overflow-wrap:anywhere]">{{row.name}}</div>
  <span v-else-if="column.key==='moduleName'" class="break-words">{{moduleLabel(row.module,catalog.artifacts.find(item=>item.key===row.module)?.name??row.module)}}</span>
  <template v-else-if="column.key==='state'">
   <PlacementStatusDetails v-if="row.operation" :operation="row.operation" :state="row.state" :name="row.name"><Button type="button" variant="ghost" size="xs" class="h-auto min-w-0 p-0 hover:bg-transparent" :aria-label="placementStatus(row.state,row.sequence).label+'. Сведения о состоянии: '+row.name"><StatusBadge :label="placementStatus(row.state,row.sequence).label" :tone="placementStatus(row.state,row.sequence).tone"/></Button></PlacementStatusDetails>
   <StatusBadge v-else :label="placementStatus(row.state,row.sequence).label" :tone="placementStatus(row.state,row.sequence).tone"/>
  </template>
  <div v-else-if="column.key==='limits'" class="text-xs tabular-nums leading-4"><span class="block">{{row.limits.memory_bytes/1024**2}} MiB</span><span class="block text-muted-foreground">{{row.limits.cpu_millis/1000}} CPU</span></div>
  <PlacementOperation v-else-if="column.key==='actions'" :operation="row.operation" :state="row.state" :module="row.module" :name="row.name" :busy="busy" :recovering="recovering===row.id" @edit="openUpdate(row)" @reconcile="reconcile(row)" @recover="recover(row)"/>
 </template>
 </DataTable>
 </DialogContent></Dialog>
 <EditorDialog :open="editor" :title="updating ? 'Настроить размещение MCP' : 'Добавить MCP в проект'" :description="updating ? 'Изменения сборки, конфигурации или лимитов заменят только этот контейнер и завершат его активные сеансы. Рабочая папка сохранится.' : 'Нода загрузит одобренный образ и запустит один контейнер с указанными лимитами. Рабочая папка сохраняется отдельно от контейнера.'" :busy="busy" :disabled="!valid||!changed" :error="formError" :submit-label="updating?'Сохранить':'Запустить'" @update:open="value=>editor=value" @submit="place">
 <p v-if="updating&&!release" role="alert" class="text-sm text-destructive">Текущая сборка отсутствует в каталоге. Выберите сборку явно.</p>
 <p v-else-if="updating&&!changed" class="text-sm text-muted-foreground">Изменений нет. Контейнер продолжает работать.</p>
 <label class="block space-y-1 text-sm">Название<Input v-model="name" :disabled="!!updating" maxlength="128"/></label>
 <label class="block space-y-1 text-sm">Сборка<Select v-model="release"><SelectTrigger><SelectValue/></SelectTrigger><SelectContent><SelectGroup v-for="section in releaseSections" :key="section.id"><SelectLabel>{{section.name}}</SelectLabel><SelectItem v-for="item in section.releases" :key="item.id" :value="item.id">{{moduleName(item.module,catalog.artifacts.find(artifact=>artifact.key===item.module)?.name??item.module)}} · {{item.source_commit.slice(0,8)}} · {{item.image.split('@sha256:')[1]?.slice(0,12)}}</SelectItem></SelectGroup></SelectContent></Select></label>
 <PlacementConfiguration v-if="['web','serena'].includes(selectedModule)" v-model="configuration" :module="selectedModule"/>
 <ProjectWorkspaceSelector v-if="['web','reverse'].includes(selectedModule)" :read-only-required="selectedModule==='reverse'" v-model="projectWorkspace" :workspaces="workspaces" :busy="workspaceBusy||busy" :error="workspaceError" @create="ensureWorkspace"/>
 <label class="block space-y-1 text-sm">Память, MiB<Input v-model="memory" type="number" min="64"/></label>
 <label class="block space-y-1 text-sm">CPU, тысячные доли ядра<Input v-model="cpu" type="number" min="100"/></label>
 <label class="block space-y-1 text-sm">Лимит процессов<Input v-model="pids" type="number" min="32"/></label>
 </EditorDialog>
</template>
