<script setup lang="ts">
import {computed,onScopeDispose,ref} from 'vue'
import type {ModuleArtifact,ModuleCatalog,ModuleImage,LogicalModule as CatalogModule} from '@/entities/node/model/modules'
import {nodeCommand} from '../api/nodes'
import {placementStateSummary} from '../model/module-presentation'
import ModuleComponentsDialog from './ModuleComponentsDialog.vue'
import {useLiveQuery} from '@/shared/lib/use-live-query'
import DataTable from '@/shared/ui/data-table/DataTable.vue'
import EditorDialog from '@/shared/ui/EditorDialog.vue'
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription} from '@/shared/ui/dialog'
import {Button} from '@/shared/ui/button'
import {Input} from '@/shared/ui/input'
import {Badge} from '@/shared/ui/badge'

const props=defineProps<{projectId:string}>()
const emit=defineEmits<{close:[]}>()
const artifacts=ref<ModuleArtifact[]>([]),releases=ref<ModuleImage[]>([]),loading=ref(false),error=ref('')
const modules=ref<CatalogModule[]>([])
const placements=ref<{module:string;state:string}[]>([])
interface LogicalModule {id:string;name:string;modules:string[];components:ModuleArtifact[]}
const details=ref<LogicalModule|null>(null)
const publication=ref<ModuleArtifact|null>(null),busy=ref(false),formError=ref('')
const commit=ref(''),fingerprint=ref(''),image=ref('')
let operation=crypto.randomUUID(),releaseId=crypto.randomUUID(),disposed=false
onScopeDispose(()=>{disposed=true})
async function read(){
 loading.value=true
 try{
  const [result,current]=await Promise.all([
   nodeCommand<ModuleCatalog>(props.projectId,{operation_uuid:crypto.randomUUID(),action:'modules',module:{action:'catalog'}}),
   nodeCommand<{items:{module:string;state:string}[]}>(props.projectId,{operation_uuid:crypto.randomUUID(),action:'modules',module:{action:'placements'}})])
  if(!Array.isArray(result.modules)||!Array.isArray(result.artifacts)||!Array.isArray(result.releases))throw new Error('CATALOG_INVALID')
  if(!disposed){modules.value=result.modules;artifacts.value=result.artifacts;releases.value=result.releases;placements.value=current.items;error.value=''}
 }catch{if(!disposed)error.value='Не удалось получить каталог образов MCP.'}
 finally{if(!disposed)loading.value=false}
}
const live=useLiveQuery(read,{enabled:()=>!!props.projectId,topics:['management.events'],accept:event=>event.type==='node.modules'||event.type.startsWith('node.module.')})
const rows=computed<LogicalModule[]>(()=>modules.value.map(module=>({id:module.key,name:module.name,modules:module.components,components:artifacts.value.filter(item=>module.components.includes(item.key))})))
function availability(row:LogicalModule){
 const available=row.components.filter(item=>item.node_adapter).length
 return row.modules.length===1?(available?'Доступен':'Не готов'):`Доступен ${available} из ${row.modules.length}`
}
function imageCount(row:LogicalModule){return releases.value.filter(item=>row.modules.includes(item.module)).length}
const valid=computed(()=>/^[a-f0-9]{40}$/.test(commit.value)&&/^[a-f0-9]{64}$/.test(fingerprint.value)&&/^[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}$/.test(image.value))
function open(artifact:ModuleArtifact){publication.value=artifact;commit.value='';fingerprint.value='';image.value='';formError.value='';operation=crypto.randomUUID();releaseId=crypto.randomUUID()}
async function publish(){
 if(!publication.value||busy.value||!valid.value)return
 busy.value=true;formError.value=''
 try{
  await nodeCommand(props.projectId,{operation_uuid:operation,action:'modules',module:{action:'publish',publication:{id:releaseId,module:publication.value.key,source_commit:commit.value,input_fingerprint:fingerprint.value,image:image.value,platform:publication.value.inputs.platform}}})
  publication.value=null;live.invalidate()
 }catch{formError.value='Публикация не подтверждена. Проверьте registry, digest и неизменность сборки; повтор использует тот же идентификатор операции.'}
 finally{busy.value=false}
}
</script>
<template>
 <Dialog :open="true" @update:open="value=>{if(!value&&!busy)emit('close')}"><DialogContent class="min-w-0 w-[calc(100vw-2rem)] max-w-[calc(100vw-2rem)] max-h-[90vh] overflow-y-auto sm:max-w-4xl [&>*]:min-w-0 [&>*]:max-w-full"><DialogHeader class="min-w-0 max-w-full"><DialogTitle>Образы MCP</DialogTitle><DialogDescription class="whitespace-normal break-words">Независимые компоненты ноды и одобренные неизменяемые сборки. Публикация образа сама по себе не запускает MCP. Состояние конкретного контейнера показывается в размещениях проекта.</DialogDescription></DialogHeader>
 <p v-if="error" role="alert" class="text-sm text-destructive">{{error}}</p>
 <DataTable class="min-w-0 max-w-full" :rows="rows" :loading="loading" label="Каталог MCP" :search-text="row=>row.name+' '+row.components.map(item=>item.name).join(' ')" selectable @select="row=>details=row" :columns="[{key:'name',title:'Модуль',dataIndex:'name'},{key:'state',title:'Адаптер'},{key:'images',title:'Образы'},{key:'runtime',title:'В проекте'},{key:'actions',title:'Действия'}]">
  <template #cell="{row,column}"><span v-if="column.key==='name'" class="whitespace-nowrap">{{row.name}}</span><Badge v-else-if="column.key==='state'" variant="outline" class="whitespace-nowrap">{{availability(row)}}</Badge><Button v-else-if="column.key==='images'" variant="ghost" size="sm" class="h-7 whitespace-nowrap px-1" @click="details=row">{{imageCount(row)}} опубликовано</Button><span v-else-if="column.key==='runtime'" class="whitespace-nowrap">{{placementStateSummary(placements,row.modules)}}</span><Button v-else-if="column.key==='actions'&&row.id!=='development'&&row.components.length===1&&row.components[0]?.node_adapter" size="sm" variant="outline" @click="open(row.components[0]!)">Опубликовать</Button><Button v-else-if="column.key==='actions'" size="sm" variant="outline" @click="details=row">{{row.id==='development'?'Компоненты':'Подробнее'}}</Button></template>
 </DataTable>
 </DialogContent></Dialog>
 <ModuleComponentsDialog :open="!!details" :single="details?.id!=='development'" :title="details?.name??''" :components="details?.components??[]" :releases="releases" :placements="placements" @close="details=null" @publish="open"/>
 <EditorDialog :open="!!publication" :title="'Публикация: '+(publication?.name??'')" description="Укажите существующий образ из разрешённого registry и данные его сборки. Идентификатор digest закрепляется и не изменяется после публикации." :busy="busy" :disabled="!valid" :error="formError" submit-label="Опубликовать" @update:open="value=>{if(!value)publication=null}" @submit="publish">
  <label class="block space-y-1 text-sm">Образ с digest<Input v-model="image" maxlength="512" placeholder="registry/repository@sha256:…"/></label>
  <label class="block space-y-1 text-sm">Коммит исходников<Input v-model="commit" maxlength="40"/></label>
  <label class="block space-y-1 text-sm">SHA256 входных файлов сборки<Input v-model="fingerprint" maxlength="64"/></label>
  <p class="text-xs text-muted-foreground">{{publication?.inputs.platform}} · {{publication?.inputs.dockerfile}}</p>
 </EditorDialog>
</template>
