<script setup lang="ts">
import {computed,ref,watch,useId} from 'vue'
import {AlertTriangle} from 'lucide-vue-next'
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription,DialogFooter} from '@/shared/ui/dialog'
import {Button} from '@/shared/ui/button'
import {Input} from '@/shared/ui/input'
const props=withDefaults(defineProps<{open:boolean;title:string;description:string;confirmLabel?:string;danger?:boolean;busy?:boolean;target?:string;disabled?:boolean}>(),{confirmLabel:'Подтвердить',danger:true,busy:false})
const emit=defineEmits<{'update:open':[open:boolean];confirm:[];cancel:[]}>()
const targetId=useId()
const typed=ref(''),submitted=ref(false)
watch(()=>[props.open,props.target,props.description],()=>{typed.value='';submitted.value=false},{flush:'sync'})
watch(()=>props.busy,value=>{if(!value)submitted.value=false})
const allowed=computed(()=>props.open&&!props.busy&&!props.disabled&&!submitted.value&&(!props.target||typed.value===props.target))
function confirm(){if(allowed.value){submitted.value=true;emit('confirm')}}
function close(value:boolean){if(!value&&!props.busy){emit('update:open',false);emit('cancel')}}
</script>
<template><Dialog :open="open" @update:open="close"><DialogContent class="max-w-md" @escape-key-down="event=>{if(busy)event.preventDefault()}" @interact-outside="event=>{if(busy)event.preventDefault()}"><DialogHeader><DialogTitle class="flex items-center gap-2"><AlertTriangle v-if="danger" class="size-4 text-destructive"/>{{title}}</DialogTitle><DialogDescription>{{description}}</DialogDescription></DialogHeader><form class="space-y-4" @submit.prevent="confirm"><slot/><label v-if="target" :for="targetId" class="block space-y-2 text-sm"><span>Введите «{{target}}» для подтверждения</span><Input :id="targetId" v-model="typed" autocomplete="off" :disabled="busy"/></label><DialogFooter><Button type="button" variant="outline" :disabled="busy" @click="close(false)">Отмена</Button><Button type="submit" :variant="danger?'destructive':'default'" :disabled="!allowed">{{busy?'Выполняем…':confirmLabel}}</Button></DialogFooter></form></DialogContent></Dialog></template>
