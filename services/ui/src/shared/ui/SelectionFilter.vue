<script setup lang="ts">
import {computed} from 'vue'
import {Check,ChevronsUpDown} from 'lucide-vue-next'
import {Popover,PopoverContent,PopoverTrigger} from './popover'
import {Button} from './button'
const props=defineProps<{label:string;options:{id:string;name:string}[];modelValue:string[]|null}>()
const emit=defineEmits<{'update:modelValue':[value:string[]|null]}>()
const selected=computed(()=>new Set(props.modelValue??props.options.map(option=>option.id)))
function toggle(id:string){const next=new Set(selected.value);if(next.has(id))next.delete(id);else next.add(id);emit('update:modelValue',[...next])}
</script>
<template><Popover><PopoverTrigger as-child><Button variant="outline" class="h-8 min-w-40 justify-between gap-2 text-xs" :aria-label="label"><span>{{label}}: {{modelValue===null?'все':selected.size}}</span><ChevronsUpDown class="size-3"/></Button></PopoverTrigger><PopoverContent align="start" class="w-72 p-2"><div class="mb-1 flex gap-1"><Button variant="ghost" size="sm" @click="emit('update:modelValue',null)">Все</Button><Button variant="ghost" size="sm" @click="emit('update:modelValue',[])">Снять выбор</Button></div><div class="max-h-72 overflow-y-auto"><Button v-for="option in options" :key="option.id" variant="ghost" size="sm" role="checkbox" :aria-checked="selected.has(option.id)" class="w-full justify-start gap-2" @click="toggle(option.id)"><span class="grid size-4 shrink-0 place-items-center rounded border"><Check v-if="selected.has(option.id)" class="size-3"/></span><span class="truncate">{{option.name}}</span></Button><p v-if="!options.length" class="p-2 text-xs text-muted-foreground">Нет доступных значений</p></div></PopoverContent></Popover></template>
