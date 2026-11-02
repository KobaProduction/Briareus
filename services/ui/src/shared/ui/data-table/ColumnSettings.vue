<script setup lang="ts">
import {ArrowUp,ArrowDown,Columns3} from 'lucide-vue-next'
import {useId} from "vue"
import {Checkbox} from "@/shared/ui/checkbox"
import type {DataTableColumn} from './types'
import {Popover,PopoverTrigger,PopoverContent} from '@/shared/ui/popover'
import {Button} from '@/shared/ui/button'
defineProps<{columns:DataTableColumn[];hidden:string[];label:string}>()
const columnPrefix=useId()
const emit=defineEmits<{toggle:[key:string];move:[key:string,direction:number];reset:[]}>()
</script>
<template><Popover><PopoverTrigger as-child><Button variant="outline" size="sm" class="h-8 gap-2" :aria-label="'Настроить колонки: '+label"><Columns3 class="size-3.5"/>Колонки</Button></PopoverTrigger><PopoverContent align="end" class="w-72 p-2"><p class="px-2 py-1 text-xs text-muted-foreground">Видимость и порядок колонок</p><div v-for="(column,index) in columns" :key="column.key" class="flex items-center gap-1"><label :for="columnPrefix+'-'+column.key" class="flex min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-sm px-3 py-2 text-xs hover:bg-accent"><Checkbox :id="columnPrefix+'-'+column.key" :model-value="!hidden.includes(column.key)" @update:model-value="emit('toggle',column.key)"/><span class="truncate">{{column.title||'Меню строки'}}</span></label><Button variant="ghost" size="icon" class="size-7" :aria-label="'Выше: '+(column.title||'Меню строки')" :disabled="index===0" @click="emit('move',column.key,-1)"><ArrowUp class="size-3"/></Button><Button variant="ghost" size="icon" class="size-7" :aria-label="'Ниже: '+(column.title||'Меню строки')" :disabled="index===columns.length-1" @click="emit('move',column.key,1)"><ArrowDown class="size-3"/></Button></div><slot/><Button variant="ghost" size="sm" class="mt-1 w-full" @click="emit('reset')">Вернуть стандартный вид</Button></PopoverContent></Popover></template>
