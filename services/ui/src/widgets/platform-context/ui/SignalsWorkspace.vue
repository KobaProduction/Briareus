<script setup lang="ts">
import {computed,ref,watch,useId,onScopeDispose} from 'vue'
import {eventBus} from '@/shared/events'
import {useEventJournal,signalVisible,presentSignal,signalTopics,type SignalRow} from '@/features/event-journal'
import {callStatus} from '@/entities/event'
import {Button} from '@/shared/ui/button'
import {ConnectionDiagnostics} from "@/features/event-journal"
import type {WorkspaceArea} from '@/features/workspace-scope'
import type {VerifiedPlatformContext} from '@/entities/workspace'
import {DataTable,type DataTableColumn} from "@/shared/ui/data-table"
import SelectionFilter from '@/shared/ui/SelectionFilter.vue'
import RelativeTime from '@/shared/ui/RelativeTime.vue'
import {Switch} from '@/shared/ui/switch'
import StatusBadge from '@/shared/ui/StatusBadge.vue'
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription} from '@/shared/ui/dialog'
const props=defineProps<{context:VerifiedPlatformContext;selectedProjectId:string|null;mode:'events'|'calls';area:WorkspaceArea}>()
const selectedTopics=ref<string[]|null>(null),selectedTypes=ref<string[]|null>(null)
const showDiagnostics=ref(false),metricBusy=ref(false),metricError=ref('')
const formId=useId()
let metricsGeneration=0,disposed=false
onScopeDispose(()=>{disposed=true;metricsGeneration++})
const journal=useEventJournal(computed(()=>signalTopics(props.mode,eventBus.state.metricsEnabled)),computed(()=>props.selectedProjectId),computed(()=>JSON.stringify([props.context.user.id,props.area,props.context.projects.map(project=>project.id)])))
const source=computed(()=>journal.source.value.filter(event=>signalVisible(event,{
  mode:props.mode,metricsEnabled:eventBus.state.metricsEnabled,selectedProjectId:props.selectedProjectId,
  allowSystemEvents:props.area.kind==='all'||props.area.kind==='admin',context:props.context,
})))
const topics=computed(()=>[...new Set(source.value.map(event=>event.topic))].sort().map(id=>({id,name:id})))
const types=computed(()=>[...new Set(source.value.map(event=>event.type))].sort().map(id=>({id,name:id})))
const rows=computed(()=>source.value.filter(event=>(selectedTopics.value===null||selectedTopics.value.includes(event.topic))&&(selectedTypes.value===null||selectedTypes.value.includes(event.type))).map(event=>presentSignal(event,props.context)))
type EventRow=SignalRow
const searchEvent=(row:EventRow)=>JSON.stringify(row)+' '+callStatus(row.status).label
const selected=ref<EventRow|null>(null)
watch(rows,current=>{if(selected.value&&!current.some(row=>row.id===selected.value?.id))selected.value=null},{flush:'sync'})
const tableRef=ref<{scrollToTop:()=>void}|null>(null)
function latest(){journal.showLatest();tableRef.value?.scrollToTop()}
watch(()=>JSON.stringify([props.context.user.id,props.mode,props.selectedProjectId,props.area,props.context.projects.map(project=>project.id)]),()=>{selected.value=null;metricsGeneration++;metricBusy.value=false;metricError.value=''}, {flush:'sync'})
type SignalColumn=DataTableColumn<keyof EventRow>
const columns=computed<SignalColumn[]>(()=>[
  {key:'time',title:'Время',dataIndex:'occurredAt'},
  ...(!props.selectedProjectId?[...(props.area.kind==='all'||props.area.kind==='admin'?[{key:'teamName',title:'Команда',dataIndex:'teamName'}] satisfies SignalColumn[]:[]),{key:'projectName',title:'Проект',dataIndex:'projectName'}] satisfies SignalColumn[]:[]),
  {key:'topic',title:'Тема',dataIndex:'topic'},{key:'signal',title:'Сигнал / инструмент',dataIndex:'signal'},
  ...(rows.value.some(row=>row.status!=='событие')?[{key:'status',title:'Состояние',dataIndex:'status'}] satisfies SignalColumn[]:[]),
  ...(props.mode==='calls'?[{key:'duration',title:'Длительность',dataIndex:'duration'}] satisfies SignalColumn[]:[]),
])
async function metrics(enabled:boolean):Promise<void>{
  if(metricBusy.value)return
  const run=metricsGeneration
  metricBusy.value=true;metricError.value=''
  try{await eventBus.setMetricsEnabled(enabled)}
  catch{if(!disposed&&run===metricsGeneration)metricError.value='Сервер не подтвердил подписку на метрики.'}
  finally{if(!disposed&&run===metricsGeneration)metricBusy.value=false}
}
</script>
<template>
  <div class="space-y-4">
    <h2 class="text-lg font-semibold">{{mode==='events'?'События':'Вызовы MCP'}}</h2>
    <div class="flex flex-wrap items-center gap-2">
      <SelectionFilter v-model="selectedTopics" :options="topics" label="Темы"/>
      <SelectionFilter v-model="selectedTypes" :options="types" label="Сигналы"/>
      <label :for="`${formId}-metrics`" v-if="mode==='events'" class="ml-auto flex items-center gap-2 text-xs text-muted-foreground"><Switch :id="`${formId}-metrics`" :model-value="eventBus.state.metricsEnabled" :disabled="metricBusy" aria-label="Подписаться на системные метрики" @update:model-value="value=>metrics(value)"/>Метрики системы</label>
      <label :for="`${formId}-diagnostics`" v-if="mode==='events'" class="flex items-center gap-2 text-xs text-muted-foreground"><Switch :id="`${formId}-diagnostics`" v-model="showDiagnostics" aria-label="Показать диагностику соединения"/>Диагностика</label>
    </div>
    <p v-if="metricError" role="alert" class="text-sm text-destructive">{{metricError}}</p>
    <ConnectionDiagnostics v-if="mode==='events'&&showDiagnostics" :context="context"/>
    <DataTable ref="tableRef" :key="JSON.stringify([mode,selectedProjectId,area])" mode="infinite" :auto-load="selectedTopics===null&&selectedTypes===null" :has-more="journal.more.value&&!journal.error.value" :loading-more="journal.busy.value" @load-more="journal.load" @scroll-position="top=>journal.atTop.value=top" :rows="rows" :columns="columns" :search-text="searchEvent" :label="mode==='events'?'События':'Вызовы MCP'" selectable @select="row=>selected=row">
      <template #cell="{row,column}"><RelativeTime v-if="column.key==='time'" :value="row.occurredAt"/><StatusBadge v-else-if="column.key==='status'" :label="callStatus(row.status).label" :tone="callStatus(row.status).tone"/><span v-else class="text-xs">{{column.dataIndex ? row[column.dataIndex] : ''}}</span></template>
    </DataTable>
    <div v-if="journal.error.value" role="alert" class="flex items-center gap-2 text-sm text-destructive">{{journal.error.value}}<Button variant="outline" size="sm" @click="journal.load">Повторить загрузку</Button></div>
    <Button v-if="!journal.atTop.value&&journal.pending.value" variant="outline" size="sm" @click="latest">Новые события: {{journal.pending.value}}</Button>
    <p class="text-xs text-muted-foreground">Загружено {{source.length}}. Поиск и фильтры применяются к загруженной истории. Сервер хранит до {{journal.retention.value}} последних событий.</p>
    <p v-if="journal.gap.value" role="status" class="text-xs text-muted-foreground">Часть старой истории уже удалена по сроку хранения.</p>
    <Button v-if="journal.more.value&&!journal.busy.value&&!journal.error.value" variant="ghost" size="sm" @click="journal.load">Загрузить более ранние события</Button>
    <Dialog :open="selected!==null" @update:open="value=>{if(!value)selected=null}"><DialogContent class="max-w-2xl"><DialogHeader><DialogTitle>Детали события</DialogTitle><DialogDescription>Метаданные серверного сигнала выбранной области</DialogDescription></DialogHeader><RelativeTime v-if="selected" :value="selected.occurredAt"/><pre class="max-h-96 overflow-auto rounded bg-muted p-3 text-xs">{{JSON.stringify(selected,null,2)}}</pre></DialogContent></Dialog>
  </div>
</template>
