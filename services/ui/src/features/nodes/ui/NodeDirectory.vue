<script setup lang="ts">
import {computed,onScopeDispose,ref,watch} from 'vue'
import {Plus,Server} from 'lucide-vue-next'
import type {ManagedNode} from '@/entities/node/model/types'
import type {VerifiedPlatformContext} from '@/entities/workspace/model/proof'
import {isPlatformProjectId} from '@/features/platform/api/platform-current'
import {nodeCommand,nodeInventory} from '../api/nodes'
import {useLiveQuery} from '@/shared/lib/use-live-query'
import DataTable from '@/shared/ui/data-table/DataTable.vue'
import EditorDialog from '@/shared/ui/EditorDialog.vue'
import ConfirmationDialog from '@/shared/ui/ConfirmationDialog.vue'
import RowActions from '@/shared/ui/RowActions.vue'
import {Button} from '@/shared/ui/button'
import {Input} from '@/shared/ui/input'
import {Badge} from '@/shared/ui/badge'
import {Select,SelectContent,SelectItem,SelectTrigger,SelectValue} from '@/shared/ui/select'
import NodeEnrollment from './NodeEnrollment.vue'
import ModuleCatalog from './ModuleCatalog.vue'
import NodePlacements from './NodePlacements.vue'

const props=defineProps<{context:VerifiedPlatformContext;projectId:string|null}>()
const project=computed(()=>props.context.projects.find(item=>item.id===props.projectId&&item.permissions.includes('use_resources'))??props.context.projects.find(item=>item.permissions.includes('use_resources')))
const operator=computed(()=>props.context.user.role==='operator')
const rows=ref<ManagedNode[]>([]),error=ref(''),loading=ref(false),busy=ref(false)
const editor=ref<'register'|'rename'|'budget'|null>(null),target=ref<ManagedNode|null>(null),disable=ref<ManagedNode|null>(null)
const enrollment=ref<{node:ManagedNode;action:'setup'|'pair'|'enable'}|null>(null)
const catalog=ref(false)
const placementNode=ref<ManagedNode|null>(null)
const name=ref(''),endpoint=ref(''),hostUuid=ref(''),runtimeUid=ref('2201'),memoryMb=ref('2048'),cpuMillis=ref('2000'),pids=ref('512')
const scope=ref<'personal'|'team'|'shared'>('shared'),formError=ref('')
let disposed=false,readVersion=0,operation=crypto.randomUUID(),nodeId=crypto.randomUUID()
onScopeDispose(()=>{disposed=true;readVersion++})
watch([()=>props.context.user.id,()=>project.value?.id],()=>{rows.value=[];editor.value=null;disable.value=null;enrollment.value=null;readVersion++})
async function read(){
  const id=project.value?.id,version=++readVersion
  if(!id||!operator.value)return
  loading.value=true
  try{const result=await nodeInventory(id);if(!disposed&&version===readVersion){rows.value=result;error.value=''}}
  catch{if(!disposed&&version===readVersion)error.value='Не удалось получить ноды. Проверьте доступность Resources.'}
  finally{if(!disposed&&version===readVersion)loading.value=false}
}
const live=useLiveQuery(read,{enabled:()=>operator.value&&!!project.value,topics:['management.events'],accept:event=>event.type.startsWith('node.')})
watch(()=>project.value?.id,()=>live.invalidate())
function open(kind:'register'|'rename'|'budget',node?:ManagedNode){
  editor.value=kind;target.value=node??null;name.value=node?.name??'';formError.value=''
  memoryMb.value=String((node?.budget.total.memory_bytes??2048*1024**2)/1024**2)
  cpuMillis.value=String(node?.budget.total.cpu_millis??2000);pids.value=String(node?.budget.total.pids??512)
  operation=crypto.randomUUID();nodeId=crypto.randomUUID()
}
function openDisable(node:ManagedNode){disable.value=node;operation=crypto.randomUUID()}
const budgetValid=computed(()=>Number.isInteger(Number(memoryMb.value))&&Number(memoryMb.value)>=512&&
  Number.isInteger(Number(cpuMillis.value))&&Number(cpuMillis.value)>750&&
  Number.isInteger(Number(pids.value))&&Number(pids.value)>192)
const valid=computed(()=>editor.value==='budget'?budgetValid.value:!!name.value.trim()&&(editor.value==='rename'||(
  /^https:\/\/[a-z0-9.-]+\/?$/.test(endpoint.value)&&isPlatformProjectId(hostUuid.value)&&
  Number.isInteger(Number(runtimeUid.value))&&Number(runtimeUid.value)>=2000&&budgetValid.value&&
  (scope.value!=='team'||project.value?.owner.kind==='team'))))
function selectedBudget(){return {total:{memory_bytes:Number(memoryMb.value)*1024**2,cpu_millis:Number(cpuMillis.value),pids:Number(pids.value)},
  reserved:target.value?.budget.reserved??{memory_bytes:384*1024**2,cpu_millis:750,pids:192}}}
async function save(){
  if(!project.value||busy.value||!valid.value)return
  busy.value=true;formError.value=''
  try{
    let command:Record<string,unknown>
    if(editor.value==='budget'&&target.value)command={operation_uuid:operation,action:'budget',node_uuid:target.value.id,expected_sequence:target.value.sequence,budget:selectedBudget()}
    else if(editor.value==='rename'&&target.value)command={operation_uuid:operation,action:'rename',node_uuid:target.value.id,name:name.value.trim(),expected_sequence:target.value.sequence}
    else command={operation_uuid:operation,action:'register',registration:{id:nodeId,name:name.value.trim(),scope:scope.value,
      owner_uuid:scope.value==='shared'?null:scope.value==='personal'?props.context.user.id:project.value.owner.id,
      host_uuid:hostUuid.value,runtime_uid:Number(runtimeUid.value),endpoint:endpoint.value,
      budget:selectedBudget()}}
    await nodeCommand(project.value.id,command);editor.value=null;live.invalidate()
  }catch{formError.value='Операция не подтверждена. Запись могла сохраниться; проверьте список. Изменённые параметры отправляйте новой операцией.'}
  finally{busy.value=false}
}
async function confirmDisable(){
  if(!project.value||!disable.value||busy.value)return
  busy.value=true
  try{await nodeCommand(project.value.id,{operation_uuid:operation,action:'disable',node_uuid:disable.value.id,expected_sequence:disable.value.sequence});disable.value=null;live.invalidate()}
  catch{error.value='Отключение не подтверждено сервером. Проверьте состояние ноды.'}
  finally{busy.value=false}
}
const scopeName=(value:string)=>({personal:'Личная',team:'Командная',shared:'Общая'}[value]??value)
</script>
<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-3"><div><h2 class="flex items-center gap-2 text-xl font-semibold"><Server class="size-5"/>Ноды</h2><p class="mt-1 text-sm text-muted-foreground">Серверы исполнения MCP и их ресурсы</p></div><Button v-if="operator" :disabled="!project" @click="open('register')"><Plus class="mr-2 size-4"/>Зарегистрировать ноду</Button></div>
    <p v-if="!operator" class="text-sm text-muted-foreground">Управление нодами доступно системному оператору.</p>
    <p v-else-if="!project" class="text-sm text-muted-foreground">Для регистрации выберите доступный проект. Ноды учитываются отдельно от проекта.</p>
    <template v-else><p v-if="error" role="alert" class="text-sm text-destructive">{{error}}</p>
      <DataTable :rows="rows" :loading="loading" label="Ноды" :columns="[{key:'name',title:'Название',dataIndex:'name'},{key:'scope',title:'Область',dataIndex:'scope'},{key:'state',title:'Состояние'},{key:'endpoint',title:'Адрес',dataIndex:'endpoint'},{key:'actions',title:'Действия'}]">
        <template #cell="{row,column}"><span v-if="column.key==='scope'">{{scopeName(row.scope)}}</span><Badge v-else-if="column.key==='state'" variant="outline">{{row.enabled?'Включена':row.paired?'Подключена, отключена':'Ожидает подключения'}}</Badge><RowActions v-else-if="column.key==='actions'" :label="'Действия с нодой '+row.name"><Button variant="ghost" class="w-full justify-start" @click="placementNode=row">MCP проекта</Button><Button variant="ghost" class="w-full justify-start" @click="enrollment={node:row,action:'setup'}">Параметры установки</Button><Button v-if="!row.paired" variant="ghost" class="w-full justify-start" @click="enrollment={node:row,action:'pair'}">Подключить ноду</Button><Button v-else-if="!row.enabled" variant="ghost" class="w-full justify-start" @click="enrollment={node:row,action:'enable'}">Включить ноду</Button><Button v-if="row.paired" variant="ghost" class="w-full justify-start" @click="open('budget',row)">Ресурсы ноды</Button><Button variant="ghost" class="w-full justify-start" @click="open('rename',row)">Переименовать</Button><Button variant="ghost" class="w-full justify-start text-destructive" :disabled="!row.enabled" @click="openDisable(row)">Отключить</Button></RowActions><span v-else>{{column.key==='name'?row.name:column.key==='endpoint'?row.endpoint:''}}</span></template>
      </DataTable>
      <p class="text-xs text-muted-foreground">Регистрация создаёт отключённую запись. После установки подтвердите публичный ключ и включите ноду. Подключение MCP проверяется отдельно.</p>
    </template>
    <NodeEnrollment v-if="enrollment&&project" :node="enrollment.node" :action="enrollment.action" :project-id="project.id" @changed="live.invalidate()" @close="enrollment=null"/>
    <Button v-if="operator&&project" variant="outline" @click="catalog=true">Образы MCP</Button>
    <ModuleCatalog v-if="catalog&&project" :key="project.id" :project-id="project.id" @close="catalog=false"/>
    <NodePlacements v-if="placementNode&&project" :key="project.id+placementNode.id" :node="placementNode" :project-id="project.id" @close="placementNode=null"/>
    <EditorDialog :open="editor!==null" :title="editor==='budget'?'Ресурсы ноды':editor==='rename'?'Переименовать ноду':'Регистрация ноды'" :description="editor==='budget'?'Рабочий бюджет применяется без перезапуска MCP, в пределах подготовленной ёмкости сервера.':'Запись ноды и её выделенный runtime. Регистрация сама по себе не запускает контейнеры.'" :busy="busy" :disabled="!valid" :error="formError" @update:open="value=>{if(!value)editor=null}" @submit="save">
      <label v-if="editor!=='budget'" class="block space-y-1 text-sm">Название<Input v-model="name" maxlength="128"/></label>
      <template v-if="editor==='register'"><label class="block space-y-1 text-sm">Область<Select v-model="scope"><SelectTrigger><SelectValue/></SelectTrigger><SelectContent><SelectItem value="shared">Общая</SelectItem><SelectItem value="personal">Личная</SelectItem><SelectItem value="team" :disabled="project?.owner.kind!=='team'">Командная — текущая команда проекта</SelectItem></SelectContent></Select></label><label class="block space-y-1 text-sm">HTTPS-адрес ноды<Input v-model="endpoint" placeholder="https://node.example.com"/></label><label class="block space-y-1 text-sm">UUID хоста из конфигурации установки<Input v-model="hostUuid"/></label><label class="block space-y-1 text-sm">Выделенный UID runtime<Input v-model="runtimeUid" type="number" min="2000"/></label></template><template v-if="editor==='register'||editor==='budget'">
      <label class="block space-y-1 text-sm">Общая память, MiB<Input v-model="memoryMb" type="number" min="512"/></label>
      <label class="block space-y-1 text-sm">Общий CPU, millicores<Input v-model="cpuMillis" type="number" min="751"/></label>
      <label class="block space-y-1 text-sm">Лимит процессов<Input v-model="pids" type="number" min="193"/></label>
      <p class="text-xs text-muted-foreground">Резерв контроллера и Gateway — минимум 384 MiB, 750 millicores и 192 процесса. Изменение ограничено ёмкостью, подготовленной bootstrap на сервере, и уже выделенными ресурсами MCP.</p>
      </template>
    </EditorDialog>
    <ConfirmationDialog :open="!!disable" title="Отключить ноду?" description="Новые обращения к MCP этой ноды будут закрыты. Рабочие данные не удаляются." confirm-label="Отключить" :busy="busy" danger @update:open="value=>{if(!value)disable=null}" @confirm="confirmDisable"/>
  </div>
</template>
