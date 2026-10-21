<script setup lang="ts">
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription,DialogFooter} from '@/shared/ui/dialog'
import {Button} from '@/shared/ui/button'
const props=defineProps<{open:boolean;title:string;description:string;busy?:boolean;disabled?:boolean;error?:string;submitLabel?:string}>()
const emit=defineEmits<{'update:open':[value:boolean];submit:[]}>()
function close(value:boolean){if(!props.busy)emit('update:open',value)}
</script>
<template><Dialog :open="open" @update:open="close"><DialogContent class="flex max-h-[90vh] w-[calc(100vw-2rem)] max-w-md flex-col overflow-hidden" @escape-key-down="event=>{if(busy)event.preventDefault()}" @interact-outside="event=>{if(busy)event.preventDefault()}"><DialogHeader class="shrink-0"><DialogTitle>{{title}}</DialogTitle><DialogDescription>{{description}}</DialogDescription></DialogHeader><form class="flex min-h-0 flex-col gap-4" @submit.prevent="()=>{if(!busy&&!disabled)emit('submit')}"><div class="min-h-0 overflow-y-auto pr-1"><fieldset :disabled="busy" class="min-w-0 space-y-4"><slot/></fieldset></div><p v-if="error" role="alert" class="shrink-0 text-sm text-destructive">{{error}}</p><DialogFooter class="shrink-0"><Button type="button" variant="outline" :disabled="busy" @click="close(false)">Отмена</Button><Button type="submit" :disabled="busy||disabled">{{busy?'Сохраняем…':submitLabel||'Сохранить'}}</Button></DialogFooter></form></DialogContent></Dialog></template>
