<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {eventBus,type BusEvent} from '@/shared/events/bus'
import {useEventJournal} from '@/features/events/model/use-event-journal'
import {callStatus} from '@/features/calls/model/call-status'
import {Button} from '@/shared/ui/button'
import ConnectionDiagnostics from '@/features/events/ui/ConnectionDiagnostics.vue'
import type {WorkspaceArea} from '@/features/workspace-scope/model/scope'
import type {VerifiedPlatformContext} from '@/entities/workspace/model/proof'
import DataTable from '@/shared/ui/data-table/DataTable.vue'
import SelectionFilter from '@/shared/ui/SelectionFilter.vue'
import RelativeTime from '@/shared/ui/RelativeTime.vue'
import {Switch} from '@/shared/ui/switch'
import StatusBadge from '@/shared/ui/StatusBadge.vue'
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription} from '@/shared/ui/dialog'
const props=defineProps<{context:VerifiedPlatformContext;selectedProjectId:string|null;mode:'events'|'calls';area:WorkspaceArea}>()
const selectedTopics=ref<string[]|null>(null),selectedTypes=ref<string[]|null>(null)
const showDiagnostics=ref(false),metricBusy=ref(false),metricError=ref('')
const data=(event:BusEvent)=>event.data&&typeof event.data==='object'?event.data as Record<string,unknown>:{}
const isMetric=(event:BusEvent)=>event.topic==='system.metrics'||/^(process|system)\.(snapshot|metrics)/.test(event.type)
const journal=useEventJournal(computed(()=>props.mode==='calls'?['mcp.calls']:['management.events','browser.runtime','system.notifications','platform.context','access.sessions',...(eventBus.state.metricsEnabled?['system.metrics']:[])]),computed(()=>props.selectedProjectId),computed(()=>JSON.stringify([props.context.user.id,props.area,props.context.projects.map(p=>p.id)])))
const source=computed(()=>journal.source.value.filter(event=>{
  if(props.mode==='calls'?event.topic!=='mcp.calls':event.topic==='mcp.calls')return false
  if(!eventBus.state.metricsEnabled&&isMetric(event))return false
  const project=data(event).project_id
  return typeof project==='string'?(props.selectedProjectId?project===props.selectedProjectId:props.context.projects.some(item=>item.id===project)):props.context.user.role==='operator'&&!props.selectedProjectId&&(props.area.kind==='all'||props.area.kind==='admin')
}))
const topics=computed(()=>[...new Set(source.value.map(event=>event.topic))].sort().map(id=>({id,name:id})))
const types=computed(()=>[...new Set(source.value.map(event=>event.type))].sort().map(id=>({id,name:id})))
const rows=computed(()=>source.value.filter(event=>(selectedTopics.value===null||selectedTopics.value.includes(event.topic))&&(selectedTypes.value===null||selectedTypes.value.includes(event.type))).map(event=>{
  const payload=data(event),project=props.context.projects.find(project=>project.id===payload.project_id)
  return {...event,id:event.id??event.occurredAt+event.topic+event.type,projectName:project?.name||'Система',teamName:project?(project.owner.kind==='user'?'Личные проекты':props.context.teams.find(team=>team.id===project.owner.id)?.name||'Команда'):'Система',signal:String(payload.tool??event.type),status:String(payload.status??'событие'),duration:typeof payload.duration_ms==='number'?payload.duration_ms+' мс':'—'}
}))
type EventRow=typeof rows.value[number]
const searchEvent=(row:EventRow)=>JSON.stringify(row)+' '+callStatus(row.status).label
const selected=ref<EventRow|null>(null)
const tableRef=ref<{scrollToTop:()=>void}|null>(null)
function latest(){journal.showLatest();tableRef.value?.scrollToTop()}
watch(()=>JSON.stringify([props.mode,props.selectedProjectId,props.area,props.context.projects.map(project=>project.id)]),()=>{selected.value=null})
const columns=computed(()=>[
  {key:'time',title:'Время',dataIndex:'occurredAt'},
  ...(!props.selectedProjectId?[...(props.area.kind==='all'||props.area.kind==='admin'?[{key:'teamName',title:'Команда',dataIndex:'teamName'}]:[]),{key:'projectName',title:'Проект',dataIndex:'projectName'}]:[]),
  {key:'topic',title:'Тема',dataIndex:'topic'},{key:'signal',title:'Сигнал / инструмент',dataIndex:'signal'},
  ...(rows.value.some(row=>row.status!=='событие')?[{key:'status',title:'Состояние',dataIndex:'status'}]:[]),
  ...(props.mode==='calls'?[{key:'duration',title:'Длительность',dataIndex:'duration'}]:[]),
])
async function metrics(enabled:boolean){if(metricBusy.value)return;metricBusy.value=true;metricError.value='';try{await eventBus.setMetricsEnabled(enabled)}catch{metricError.value='Сервер не подтвердил подписку на метрики.'}finally{metricBusy.value=false}}
</script>
<template>
  <div class="space-y-4">
    <h2 class="text-lg font-semibold">{{mode==='events'?'События':'Вызовы MCP'}}</h2>
    <div class="flex flex-wrap items-center gap-2">
      <SelectionFilter v-model="selectedTopics" :options="topics" label="Темы"/>
      <SelectionFilter v-model="selectedTypes" :options="types" label="Сигналы"/>
      <label v-if="mode==='events'" class="ml-auto flex items-center gap-2 text-xs text-muted-foreground"><Switch :model-value="eventBus.state.metricsEnabled" :disabled="metricBusy" aria-label="Подписаться на системные метрики" @update:model-value="value=>metrics(value)"/>Метрики системы</label>
      <label v-if="mode==='events'" class="flex items-center gap-2 text-xs text-muted-foreground"><Switch v-model="showDiagnostics" aria-label="Показать диагностику соединения"/>Диагностика</label>
    </div>
    <p v-if="metricError" role="alert" class="text-sm text-destructive">{{metricError}}</p>
    <ConnectionDiagnostics v-if="mode==='events'&&showDiagnostics" :context="context"/>
    <DataTable ref="tableRef" :key="JSON.stringify([mode,selectedProjectId,area])" mode="infinite" :auto-load="selectedTopics===null&&selectedTypes===null" :has-more="journal.more.value&&!journal.error.value" :loading-more="journal.busy.value" @load-more="journal.load" @scroll-position="top=>journal.atTop.value=top" :rows="rows" :columns="columns" :search-text="searchEvent" :label="mode==='events'?'События':'Вызовы MCP'" selectable @select="row=>selected=row">
      <template #cell="{row,column}"><RelativeTime v-if="column.key==='time'" :value="row.occurredAt"/><StatusBadge v-else-if="column.key==='status'" :label="callStatus(row.status).label" :tone="callStatus(row.status).tone"/><span v-else class="text-xs">{{row[column.dataIndex as keyof typeof row]}}</span></template>
    </DataTable>
    <div v-if="journal.error.value" role="alert" class="flex items-center gap-2 text-sm text-destructive">{{journal.error.value}}<Button variant="outline" size="sm" @click="journal.load">Повторить загрузку</Button></div>
    <Button v-if="!journal.atTop.value&&journal.pending.value" variant="outline" size="sm" @click="latest">Новые события: {{journal.pending.value}}</Button>
    <p class="text-xs text-muted-foreground">Загружено {{source.length}}. Поиск и фильтры применяются к загруженной истории. Сервер хранит до {{journal.retention.value}} последних событий.</p>
    <p v-if="journal.gap.value" role="status" class="text-xs text-muted-foreground">Часть старой истории уже удалена по сроку хранения.</p>
    <Button v-if="journal.more.value&&!journal.busy.value&&!journal.error.value" variant="ghost" size="sm" @click="journal.load">Загрузить более ранние события</Button>
    <Dialog :open="selected!==null" @update:open="value=>{if(!value)selected=null}"><DialogContent class="max-w-2xl"><DialogHeader><DialogTitle>Детали события</DialogTitle><DialogDescription>Метаданные серверного сигнала выбранной области</DialogDescription></DialogHeader><RelativeTime v-if="selected" :value="selected.occurredAt"/><pre class="max-h-96 overflow-auto rounded bg-muted p-3 text-xs">{{JSON.stringify(selected,null,2)}}</pre></DialogContent></Dialog>
  </div>
</template>
