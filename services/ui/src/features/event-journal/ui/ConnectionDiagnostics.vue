<script setup lang="ts">
import {computed} from 'vue'
import {eventBus} from '@/shared/events'
import type {VerifiedPlatformContext} from '@/entities/workspace'
import {DataTable} from "@/shared/ui/data-table"
import RelativeTime from '@/shared/ui/RelativeTime.vue'
import {Badge} from '@/shared/ui/badge'
const props=defineProps<{context:VerifiedPlatformContext}>()
const sources=computed(()=>Object.entries(eventBus.state.sources).filter(([,source])=>!source.projectId||props.context.projects.some(project=>project.id===source.projectId)).map(([id,source])=>({id,...source,projectName:source.projectId?props.context.projects.find(project=>project.id===source.projectId)?.name||'Проект':'Система',state:eventBus.state.status!=='connected'?'Ожидает соединения':source.status==='connected'?'Доступен':'Недоступен'})))
const metrics=computed(()=>[{id:'latency',name:'Задержка',value:eventBus.state.latencyMs===null?'—':eventBus.state.latencyMs+' мс'},{id:'messages',name:'Получено сообщений',value:String(eventBus.state.received)},{id:'reconnects',name:'Переподключения',value:String(eventBus.state.reconnects)},{id:'sequence',name:'Позиция потока',value:String(eventBus.state.lastSequence)},{id:'gaps',name:'Пропуски доставки',value:String(eventBus.state.deliveryGaps)}])
</script>
<template><div class="grid min-w-0 gap-5 xl:grid-cols-[2fr_1fr]"><section class="min-w-0 space-y-2"><h3 class="text-sm font-medium">Источники событий</h3><DataTable :rows="sources" :columns="[{key:'source',title:'Источник',dataIndex:'source'},{key:'projectName',title:'Проект',dataIndex:'projectName'},{key:'state',title:'Состояние',dataIndex:'state'},{key:'time',title:'Последний сигнал',dataIndex:'lastEventAt'}]" label="Источники событий"><template #cell="{row,column}"><RelativeTime v-if="column.key==='time'&&row.lastEventAt" :value="row.lastEventAt"/><Badge v-else-if="column.key==='state'" variant="outline" :class="row.state==='Доступен'?'text-emerald-400':'text-amber-400'">{{row.state}}</Badge><span v-else class="text-xs">{{column.dataIndex ? row[column.dataIndex] : ''}}</span></template></DataTable></section><section class="min-w-0 space-y-2"><h3 class="text-sm font-medium">Диагностика потока</h3><DataTable :rows="metrics" :columns="[{key:'name',title:'Показатель',dataIndex:'name'},{key:'value',title:'Значение',dataIndex:'value'}]" label="Диагностика потока"/></section></div></template>
