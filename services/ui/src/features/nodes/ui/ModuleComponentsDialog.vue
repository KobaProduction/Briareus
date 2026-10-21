<script setup lang="ts">
import type {ModuleArtifact,ModuleImage} from '@/entities/node/model/modules'
import {moduleName,placementStateSummary} from '../model/module-presentation'
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription} from '@/shared/ui/dialog'
import {Table,TableHeader,TableHead,TableBody,TableRow,TableCell} from '@/shared/ui/table'
import {Button} from '@/shared/ui/button'
import {Badge} from '@/shared/ui/badge'
import RelativeTime from '@/shared/ui/RelativeTime.vue'
defineProps<{open:boolean;title:string;components:ModuleArtifact[];releases:ModuleImage[];placements:{module:string;state:string}[];single?:boolean}>()
const emit=defineEmits<{close:[];publish:[component:ModuleArtifact]}>()
</script>
<template>
 <Dialog :open="open" @update:open="value=>{if(!value)emit('close')}"><DialogContent class="min-w-0 w-[calc(100vw-2rem)] max-w-[calc(100vw-2rem)] max-h-[90vh] overflow-y-auto sm:max-w-4xl [&>*]:min-w-0 [&>*]:max-w-full">
  <DialogHeader class="min-w-0"><DialogTitle>{{title}}</DialogTitle><DialogDescription class="whitespace-normal break-words">Опубликованный образ и работающий контейнер имеют отдельные состояния.</DialogDescription></DialogHeader>
  <Table v-if="!single"><TableHeader><TableRow><TableHead>Компонент</TableHead><TableHead>Адаптер</TableHead><TableHead>Образы</TableHead><TableHead>В проекте</TableHead><TableHead>Действия</TableHead></TableRow></TableHeader><TableBody><TableRow v-for="component in components" :key="component.key">
   <TableCell class="whitespace-nowrap">{{moduleName(component.key,component.name)}}</TableCell><TableCell><Badge variant="outline" class="whitespace-nowrap">{{component.node_adapter?'Доступен':'Не готов'}}</Badge></TableCell><TableCell class="whitespace-nowrap">{{releases.filter(item=>item.module===component.key).length}} опубликовано</TableCell><TableCell class="whitespace-nowrap">{{placementStateSummary(placements,[component.key])}}</TableCell><TableCell><Button v-if="component.node_adapter" size="sm" variant="outline" @click="emit('publish',component)">Опубликовать</Button></TableCell>
  </TableRow></TableBody></Table>
  <details v-for="component in components" :key="component.key" :open="single" class="min-w-0 text-sm"><summary class="cursor-pointer py-1">{{single?'Опубликованные образы':moduleName(component.key,component.name)+' · опубликованные образы'}}</summary>
   <p v-if="!releases.some(item=>item.module===component.key)" class="py-2 text-muted-foreground">Опубликованных образов пока нет.</p>
   <Table v-else><TableHeader><TableRow><TableHead>Коммит</TableHead><TableHead>Образ</TableHead><TableHead>Опубликован</TableHead></TableRow></TableHeader><TableBody><TableRow v-for="item in releases.filter(item=>item.module===component.key)" :key="item.id"><TableCell class="font-mono">{{item.source_commit.slice(0,8)}}</TableCell><TableCell class="max-w-96"><span class="block truncate font-mono text-xs" :title="item.image">{{item.image}}</span></TableCell><TableCell class="whitespace-nowrap"><RelativeTime :value="item.created_at"/></TableCell></TableRow></TableBody></Table>
  </details>
 </DialogContent></Dialog>
</template>
