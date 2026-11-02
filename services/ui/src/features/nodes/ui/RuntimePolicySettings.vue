<script setup lang="ts">
import {useId} from "vue"
const formId=useId()
import {nodeGateway} from "../api/nodes"
import EditorDialog from '@/shared/ui/EditorDialog.vue'
import {Button} from '@/shared/ui/button'
import {Input} from '@/shared/ui/input'
import {Select,SelectContent,SelectItem,SelectTrigger,SelectValue} from '@/shared/ui/select'
import {useRuntimePolicy} from "../model/use-runtime-policy"

const props=defineProps<{projectId:string;nodeId:string}>()
const {open,scope,busy,error,policy,modes,values,submitted,valid,fields,load,show,save}=useRuntimePolicy(props,nodeGateway)
</script>
<template><Button variant="outline" size="sm" @click="show">Правила выполнения</Button><EditorDialog :open="open" title="Правила выполнения MCP" description="Нода переопределяет сервер. При отсутствии таймаута выполнение не ограничивается по времени; срок действия прав остаётся обязательным." :busy="busy" :disabled="!valid" :error="error" submit-label="Сохранить" @update:open="v=>open=v" @submit="save">
<label :for="`${formId}-scope`" class="block space-y-1 text-sm">Область настройки<Select v-model="scope" :disabled="busy||!!submitted" @update:model-value="load"><SelectTrigger :id="`${formId}-scope`"><SelectValue/></SelectTrigger><SelectContent><SelectItem value="server">Весь Briareus</SelectItem><SelectItem value="node">Эта нода</SelectItem></SelectContent></Select></label>
<div v-for="f in fields" :key="f.key" class="space-y-2 border-t pt-3"><label :for="`${formId}-${f.key}-mode`" class="block text-sm font-medium">{{f.label}}</label><div class="flex gap-2"><Select v-model="modes[f.key]" :disabled="busy||!policy||!!submitted"><SelectTrigger :id="`${formId}-${f.key}-mode`" :aria-label="f.label"><SelectValue/></SelectTrigger><SelectContent><SelectItem value="inherit">{{scope==='node'?'Наследовать сервер':'По умолчанию'}}</SelectItem><SelectItem value="none">Без ограничения</SelectItem><SelectItem value="value">Задать значение</SelectItem></SelectContent></Select><Input v-if="modes[f.key]==='value'" v-model="values[f.key]" type="number" min="1" :step="f.key==='web_max_tabs'?1:'any'" :disabled="busy||!!submitted" :aria-label="f.label+' · '+f.unit" class="max-w-32"/></div><p v-if="policy" class="text-xs text-muted-foreground">Сохранённое эффективное значение: {{policy.effective[f.key]??'без ограничения'}} {{policy.effective[f.key]===null?'':f.unit}} · {{policy.sources[f.key]==='node'?'нода':policy.sources[f.key]==='server'?'сервер':'по умолчанию'}}</p></div>
<div v-if="submitted&&error" class="space-y-2 text-sm"><p>Сохранённая команда доступна для точного повтора. Для изменения параметров сначала получите текущее состояние сервера.</p><Button type="button" variant="outline" :disabled="busy" @click="load">Получить текущее состояние</Button></div>
<p class="text-xs text-muted-foreground">Действующие процессы сохраняются. Новые правила применяются при следующем обновлении размещения MCP.</p>
</EditorDialog></template>
