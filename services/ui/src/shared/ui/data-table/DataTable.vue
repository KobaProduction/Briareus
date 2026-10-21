<script setup lang="ts" generic="T extends {id:string}">
// HTTP Bridge DataTable (repair b89c5f6): reactive TanStack row model and
// sorting. The renderer uses the current shadcn Table instead of Ant Design.
import {computed,ref,watch,onMounted,onBeforeUnmount,nextTick} from "vue"
import {createSortedRowModel,rowSortingFeature,sortFn_alphanumeric,tableFeatures,useTable,type ColumnDef} from "@tanstack/vue-table"
import {ArrowDown,ArrowUp,ChevronsUpDown,ChevronLeft,ChevronRight} from "lucide-vue-next"
import ColumnSettings from "./ColumnSettings.vue"
import {useColumnLayout} from "./use-column-layout"
import type {DataTableColumn} from "./types"
import {Input} from "@/shared/ui/input"
import {Button} from "@/shared/ui/button"
import {Table,TableHeader,TableHead,TableBody,TableRow,TableCell} from "@/shared/ui/table"
const props=withDefaults(defineProps<{columns:DataTableColumn[];rows:T[];label:string;pageSize?:number;loading?:boolean;selectable?:boolean;searchText?:(row:T)=>string;mode?:"pages"|"infinite";hasMore?:boolean;loadingMore?:boolean;autoLoad?:boolean}>(),{pageSize:25,autoLoad:true})
const emit=defineEmits<{select:[row:T];loadMore:[];scrollPosition:[top:boolean]}>()
const {ordered,visible:visibleColumns,hidden,toggle,move,reset}=useColumnLayout(()=>props.columns,()=>props.label)
const search=ref(''),page=ref(1)
function activate(event:MouseEvent|KeyboardEvent,row:T){if(!props.selectable)return;const target=event.target as HTMLElement;if(target.closest('button,a,input,select,textarea,summary,[role=button],[role=checkbox]'))return;if(event instanceof KeyboardEvent){if(event.target!==event.currentTarget)return;event.preventDefault()}emit('select',row)}
const features=tableFeatures({rowSortingFeature,sortedRowModel:createSortedRowModel(),sortFns:{alphanumeric:sortFn_alphanumeric}})
const columns=computed<ColumnDef<typeof features,T>[]>(()=>visibleColumns.value.map(column=>({id:column.key,accessorFn:row=>column.dataIndex?(row as Record<string,unknown>)[column.dataIndex]:undefined,header:column.title,enableSorting:column.sortable??!!column.dataIndex,sortFn:'alphanumeric'})))
const data=computed(()=>{
  const token=search.value.trim().toLocaleLowerCase()
  return token?props.rows.filter(row=>props.searchText?.(row).toLocaleLowerCase().includes(token)||props.columns.some(column=>column.dataIndex&&String((row as Record<string,unknown>)[column.dataIndex]??'').toLocaleLowerCase().includes(token))):props.rows
})
const table=useTable({features,columns,data,getRowId:(row:T)=>row.id})
const sorted=computed(()=>table.getRowModel().rows)
const pages=computed(()=>Math.max(1,Math.ceil(sorted.value.length/props.pageSize)))
const viewport=ref<HTMLElement|null>(null),scrollTop=ref(0),viewportHeight=ref(480)
const rowHeight=44,overscan=8
const first=computed(()=>props.mode==='infinite'?Math.max(0,Math.floor(scrollTop.value/rowHeight)-overscan):0)
const end=computed(()=>Math.min(sorted.value.length,first.value+Math.ceil(viewportHeight.value/rowHeight)+overscan*2))
const visible=computed(()=>props.mode==='infinite'?sorted.value.slice(first.value,end.value):sorted.value.slice((page.value-1)*props.pageSize,page.value*props.pageSize))
function scroll(){if(!viewport.value)return;scrollTop.value=viewport.value.scrollTop;emit('scrollPosition',scrollTop.value<5);if(props.mode==='infinite'&&props.autoLoad&&!search.value&&props.hasMore&&!props.loadingMore&&viewport.value.scrollHeight-viewport.value.scrollTop-viewport.value.clientHeight<300)emit('loadMore')}
function scrollToTop(){scrollTop.value=0;if(viewport.value)viewport.value.scrollTop=0;emit('scrollPosition',true)}
defineExpose({scrollToTop})
let observer:ResizeObserver|undefined
onMounted(()=>{if(viewport.value){observer=new ResizeObserver(()=>{viewportHeight.value=viewport.value?.clientHeight??480});observer.observe(viewport.value)}})
onBeforeUnmount(()=>observer?.disconnect())
watch(()=>[props.rows.length,props.hasMore,props.loadingMore],async()=>{await nextTick();if(props.mode==='infinite'&&viewport.value&&viewport.value.scrollHeight<=viewport.value.clientHeight+1)scroll()})
watch(search,()=>{page.value=1;scrollTop.value=0;if(viewport.value)viewport.value.scrollTop=0})
watch(pages,value=>{page.value=Math.min(page.value,value)})
function value(row:T,column:DataTableColumn){return column.dataIndex?(row as Record<string,unknown>)[column.dataIndex]:''}
</script>
<template>
  <div class="space-y-2" :aria-label="label" :aria-busy="loading">
    <div class="flex items-center justify-between gap-3"><Input v-model="search" class="h-8 max-w-xs" :aria-label="`Поиск: ${label}`" placeholder="Поиск…"/><div class="flex items-center gap-3"><span class="text-xs tabular-nums text-muted-foreground">{{sorted.length}}</span><ColumnSettings :columns="ordered" :hidden="hidden" :label="label" @toggle="toggle" @move="move" @reset="reset"><slot name="settings"/></ColumnSettings></div></div>
    <div ref="viewport" :class="mode==='infinite'?'max-h-[65vh] min-h-40 overflow-auto':''" @scroll="scroll"><Table><TableHeader :class="mode==='infinite'?'sticky top-0 z-10 bg-background':''"><TableRow><TableHead v-for="column in visibleColumns" :key="column.key" :aria-sort="table.getColumn(column.key)?.getIsSorted()==='asc'?'ascending':table.getColumn(column.key)?.getIsSorted()==='desc'?'descending':'none'">
      <Button v-if="table.getColumn(column.key)?.getCanSort()" variant="ghost" size="sm" class="-ml-2 h-8 gap-1 px-2" @click="table.getColumn(column.key)?.toggleSorting()">{{column.title}}<ArrowUp v-if="table.getColumn(column.key)?.getIsSorted()==='asc'" class="size-3"/><ArrowDown v-else-if="table.getColumn(column.key)?.getIsSorted()==='desc'" class="size-3"/><ChevronsUpDown v-else class="size-3 opacity-40"/></Button><span v-else>{{column.title}}</span>
    </TableHead></TableRow></TableHeader><TableBody><TableRow v-if="mode==='infinite'&&first>0" aria-hidden="true"><TableCell :colspan="visibleColumns.length" class="p-0" :style="{height:first*rowHeight+'px'}"/></TableRow><TableRow v-for="row in visible" :key="row.id" :tabindex="selectable?0:undefined" :class="selectable?'cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring':undefined" @click="(event:MouseEvent)=>activate(event,row.original)" @keydown.enter="(event:KeyboardEvent)=>activate(event,row.original)" @keydown.space="(event:KeyboardEvent)=>activate(event,row.original)"><TableCell v-for="column in visibleColumns" :key="column.key" class="py-2 text-sm" :class="mode==='infinite'?'h-11 max-w-64 truncate whitespace-nowrap':''"><slot name="cell" :row="row.original" :column="column"><span>{{value(row.original,column)}}</span></slot></TableCell></TableRow><TableRow v-if="mode==='infinite'&&end<sorted.length" aria-hidden="true"><TableCell :colspan="visibleColumns.length" class="p-0" :style="{height:(sorted.length-end)*rowHeight+'px'}"/></TableRow><TableRow v-if="!visible.length"><TableCell :colspan="visibleColumns.length" class="h-20 text-center text-muted-foreground">{{loading?'Загружаем…':search?'Совпадений нет':'Записей пока нет'}}</TableCell></TableRow></TableBody></Table></div>
    <div v-if="mode!=='infinite'&&pages>1" class="flex items-center justify-end gap-2 text-xs text-muted-foreground"><span>{{page}} / {{pages}}</span><Button size="icon-sm" variant="ghost" aria-label="Предыдущая страница" :disabled="page===1" @click="page--"><ChevronLeft/></Button><Button size="icon-sm" variant="ghost" aria-label="Следующая страница" :disabled="page===pages" @click="page++"><ChevronRight/></Button></div>
    <p v-if="mode==='infinite'&&loadingMore" role="status" class="text-xs text-muted-foreground">Загружаем продолжение…</p>
  </div>
</template>
