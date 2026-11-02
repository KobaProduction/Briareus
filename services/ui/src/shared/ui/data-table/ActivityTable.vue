<script setup lang="ts">
import {computed,ref,watch,useId} from 'vue'
import DataTable from './DataTable.vue'
import type {ActivityRow} from './activity'
import type {DataTableColumn} from './types'
import RowActions from '@/shared/ui/RowActions.vue'
import RelativeTime from '@/shared/ui/RelativeTime.vue'
import DetailHoverCard from '@/shared/ui/DetailHoverCard.vue'
import {Button} from '@/shared/ui/button'
import {Badge} from '@/shared/ui/badge'
import {Switch} from '@/shared/ui/switch'
import {Select,SelectTrigger,SelectValue,SelectContent,SelectItem} from '@/shared/ui/select'
const props=defineProps<{rows:ActivityRow[];projectNames:Record<string,string>;showProject:boolean;loading:boolean;label:string}>()
const showSystemId=useId()
const status=ref('all'),module=ref('all'),operation=ref('all'),showSystem=ref(false)
const statuses=computed(()=>[...new Set(props.rows.map(row=>row.status))])
const modules=computed(()=>[...new Map(props.rows.flatMap(row=>(row.permissions??[]).filter(group=>showSystem.value||!group.system).map<[string,string]>(group=>[group.id,group.title]))).entries()])
watch(()=>props.label,()=>{status.value='all';module.value='all';operation.value='all'})
watch(showSystem,value=>{if(!value){if(module.value==='project')module.value='all';if(props.rows.some(row=>row.permissions?.some(group=>group.system&&group.operations.includes(operation.value))))operation.value='all'}})
const operations=computed(()=>[...new Map(props.rows.flatMap(row=>(row.permissions??[]).filter(group=>(showSystem.value||!group.system)&&(module.value==='all'||module.value===group.id)).flatMap(group=>group.operations.map<[string,string]>((code,index)=>[code,group.title+' · '+(group.actions[index]||code)])))).entries()])
watch(module,()=>{operation.value='all'})
function permissions(row:ActivityRow){return (row.permissions??[]).filter(group=>(showSystem.value||!group.system)&&(module.value==='all'||module.value===group.id)&&(operation.value==='all'||group.operations.includes(operation.value)))}
const displayRows=computed(()=>props.rows.filter(row=>(status.value==='all'||row.status===status.value)&&(module.value==='all'&&operation.value==='all'||permissions(row).length>0)).map(row=>({...row,projectName:props.projectNames[row.projectId]||'Проект',description:row.description||'',modules:permissions(row).map(group=>group.title).join(', '),operations:permissions(row).map(group=>group.actions.join(', ')).join('; ')})))
type ActivityColumn=DataTableColumn<keyof (typeof displayRows.value)[number]>
const columns=computed<ActivityColumn[]>(()=>[
  ...(props.showProject?[{key:'projectName',title:'Проект',dataIndex:'projectName'}] satisfies ActivityColumn[]:[]),
  {key:'name',title:props.label==='Сеансы'?'Сеанс':'Заявка',dataIndex:'name'},
  {key:'actor',title:'Инициатор',dataIndex:'actor'},
  {key:'modules',title:'MCP-модули',dataIndex:'modules'},
  {key:'operations',title:'Действия',dataIndex:'operations'},
  {key:'description',title:'Описание',dataIndex:'description'},
  {key:'status',title:'Состояние',dataIndex:'status'},
  {key:'expires',title:'Срок',dataIndex:'expires'},
  {key:'actions',title:'',sortable:false},
])
const colors:Record<string,string>={active:'border-emerald-500/30 bg-emerald-500/10 text-emerald-400',approved:'border-emerald-500/30 bg-emerald-500/10 text-emerald-400',pending:'border-amber-500/30 bg-amber-500/10 text-amber-400',revoked:'border-rose-500/30 bg-rose-500/10 text-rose-400',rejected:'border-rose-500/30 bg-rose-500/10 text-rose-400',expired:'border-zinc-500/30 bg-zinc-500/10 text-zinc-400'}
function searchText(row:ActivityRow&{projectName:string}){return [row.id,row.sessionId,row.actor,row.description,row.projectName,...(row.permissions??[]).filter(group=>showSystem.value||!group.system).flatMap(group=>[group.title,...group.actions,...group.tools,...group.operations])].join(' ')}
</script>
<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-center gap-2">
      <Select v-model="status"><SelectTrigger class="h-8 w-40" aria-label="Фильтр состояния"><SelectValue/></SelectTrigger><SelectContent><SelectItem value="all">Все состояния</SelectItem><SelectItem v-for="value in statuses" :key="value" :value="value">{{value}}</SelectItem></SelectContent></Select>
      <Select v-model="module"><SelectTrigger class="h-8 w-48" aria-label="Фильтр MCP-модуля"><SelectValue placeholder="Все MCP-модули"/></SelectTrigger><SelectContent><SelectItem value="all">Все MCP-модули</SelectItem><SelectItem v-for="[id,title] in modules" :key="id" :value="id">{{title}}</SelectItem></SelectContent></Select>
      <Select v-model="operation"><SelectTrigger class="h-8 w-48" aria-label="Фильтр действия"><SelectValue/></SelectTrigger><SelectContent><SelectItem value="all">Все действия</SelectItem><SelectItem v-for="[code,title] in operations" :key="code" :value="code">{{title}}</SelectItem></SelectContent></Select>
    </div>
    <DataTable :key="label" :rows="displayRows" :columns="columns" :search-text="searchText" :loading="loading" :label="label" selectable @select="row=>row.inspect?.()">
      <template #settings><div class="mt-2 space-y-2 border-t px-2 pt-3"><label :for="showSystemId" class="flex items-center justify-between gap-2 text-xs"><span>Служебные права</span><Switch :id="showSystemId" v-model="showSystem" aria-label="Показать внутренние права чтения метаданных проекта"/></label><p class="text-xs leading-4 text-muted-foreground">Показывает внутренние операции, например чтение метаданных проекта. На выданные права не влияет.</p></div></template>
      <template #cell="{row,column}">
        <RowActions v-if="column.key==='actions'" :label="'Действия: '+row.name"><Button v-for="action in row.actions" :key="action.label" variant="ghost" size="sm" class="w-full justify-start" :disabled="action.disabled" @click="action.run">{{action.label}}</Button></RowActions>
        <Badge v-else-if="column.key==='status'" variant="outline" :class="colors[row.statusCode||'']">{{row.status}}</Badge>
        <DetailHoverCard v-else-if="column.key==='name'">
          <template #trigger><Button variant="ghost" size="sm" class="-ml-2 h-7 px-2 font-mono text-xs" @click="row.inspect?.()">{{row.name}}</Button></template>
          <p class="font-medium">{{label==='Сеансы'?'Сеанс':'Заявка'}} · {{row.projectName}}</p>
          <p class="break-all font-mono text-xs">{{row.id}}</p>
          <p v-if="row.sessionId&&row.sessionId!==row.id" class="break-all text-xs text-muted-foreground">Сеанс: {{row.sessionId}}</p>
          <p class="text-xs">Инициатор: {{row.actor}}</p>
          <p v-if="row.created" class="text-xs text-muted-foreground">Создан: {{new Date(row.created).toLocaleString()}}</p>
          <p class="whitespace-pre-wrap break-words text-sm">{{row.description||'Описание не указано'}}</p>
          <div v-for="group in permissions(row)" :key="group.id" class="text-xs"><span class="font-medium">{{group.title}}</span> · {{group.actions.join(', ')}}<p v-if="group.tools.length" class="mt-1 text-muted-foreground">{{group.tools.join(', ')}}</p></div>
        </DetailHoverCard>
        <div v-else-if="column.key==='modules'||column.key==='operations'" class="space-y-1 text-xs"><p v-for="group in permissions(row)" :key="group.id">{{column.key==='modules'?group.title:group.actions.join(', ')}}</p><span v-if="!permissions(row).length" class="text-muted-foreground">—</span></div>
        <RelativeTime v-else-if="column.key==='expires'&&row.expiresAt" :value="row.expiresAt"/>
        <span v-else-if="column.key==='description'" class="line-clamp-2 max-w-56 text-xs text-muted-foreground">{{row.description||'—'}}</span>
        <span v-else class="text-xs">{{column.dataIndex ? row[column.dataIndex] : ''}}</span>
      </template>
    </DataTable>
  </div>
</template>
