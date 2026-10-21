<script setup lang="ts">
import {computed,ref} from 'vue'
import {nodeCommand} from '../api/nodes'
import EditorDialog from '@/shared/ui/EditorDialog.vue'
import {Button} from '@/shared/ui/button'
import {Input} from '@/shared/ui/input'
import {Select,SelectContent,SelectItem,SelectTrigger,SelectValue} from '@/shared/ui/select'
const props=defineProps<{projectId:string;nodeId:string}>()
type Key='execution_timeout_seconds'|'web_max_tabs'|'web_tab_idle_seconds'|'terminal_idle_seconds'
const fields:{key:Key;label:string;unit:string}[]=[{key:'execution_timeout_seconds',label:'Таймаут выполнения MCP',unit:'секунд'},{key:'web_max_tabs',label:'Максимум вкладок браузера',unit:'вкладок'},{key:'web_tab_idle_seconds',label:'Закрывать неактивные вкладки через',unit:'секунд'},{key:'terminal_idle_seconds',label:'Завершать неактивные сеансы Terminal через',unit:'секунд'}]
interface Policy {scope:string;sequence:number;overrides:Partial<Record<Key,number|null>>;effective:Record<Key,number|null>;sources:Record<Key,string>}
const open=ref(false),scope=ref<'server'|'node'>('node'),busy=ref(false),error=ref(''),policy=ref<Policy|null>(null)
const modes=ref<Partial<Record<Key,'inherit'|'none'|'value'>>>({}),values=ref<Partial<Record<Key,string>>>({})
let operation=crypto.randomUUID()
const submitted=ref<Record<string,unknown>|null>(null)
const valid=computed(()=>!!policy.value&&fields.every(f=>modes.value[f.key]!=='value'||Number(values.value[f.key])>0&&(f.key!=='web_max_tabs'||Number.isInteger(Number(values.value[f.key])))))
async function load(){busy.value=true;error.value='';policy.value=null;submitted.value=null;operation=crypto.randomUUID();try{const result=await nodeCommand<{runtime_policy:Policy}>(props.projectId,{operation_uuid:crypto.randomUUID(),action:'runtime_policy_get',policy_scope:scope.value,node_uuid:scope.value==='node'?props.nodeId:null});policy.value=result.runtime_policy;for(const f of fields){const n=policy.value.overrides[f.key];modes.value[f.key]=n===undefined?'inherit':n===null?'none':'value';values.value[f.key]=String(n??policy.value.effective[f.key]??'')}}catch{error.value='Не удалось получить настройки выполнения.'}finally{busy.value=false}}
async function show(){open.value=true;await load()}
async function save(){if(!policy.value||!valid.value)return;busy.value=true;error.value='';const overrides:Partial<Record<Key,number|null>>={};for(const f of fields)if(modes.value[f.key]!=='inherit')overrides[f.key]=modes.value[f.key]==='none'?null:Number(values.value[f.key]);if(!submitted.value)submitted.value={operation_uuid:operation,action:'runtime_policy',policy_scope:scope.value,node_uuid:scope.value==='node'?props.nodeId:null,policy_values:overrides,expected_policy_sequence:policy.value.sequence};try{await nodeCommand(props.projectId,submitted.value);open.value=false}catch{error.value='Сохранение не подтверждено. Повтор использует ту же операцию.'}finally{busy.value=false}}
</script>
<template><Button variant="outline" size="sm" @click="show">Правила выполнения</Button><EditorDialog :open="open" title="Правила выполнения MCP" description="Нода переопределяет сервер. При отсутствии таймаута выполнение не ограничивается по времени; срок действия прав остаётся обязательным." :busy="busy" :disabled="!valid" :error="error" submit-label="Сохранить" @update:open="v=>open=v" @submit="save">
<label class="block space-y-1 text-sm">Область настройки<Select v-model="scope" :disabled="busy||!!submitted" @update:model-value="load"><SelectTrigger><SelectValue/></SelectTrigger><SelectContent><SelectItem value="server">Весь Briareus</SelectItem><SelectItem value="node">Эта нода</SelectItem></SelectContent></Select></label>
<div v-for="f in fields" :key="f.key" class="space-y-2 border-t pt-3"><label class="block text-sm font-medium">{{f.label}}</label><div class="flex gap-2"><Select v-model="modes[f.key]" :disabled="busy||!policy||!!submitted"><SelectTrigger :aria-label="f.label"><SelectValue/></SelectTrigger><SelectContent><SelectItem value="inherit">{{scope==='node'?'Наследовать сервер':'По умолчанию'}}</SelectItem><SelectItem value="none">Без ограничения</SelectItem><SelectItem value="value">Задать значение</SelectItem></SelectContent></Select><Input v-if="modes[f.key]==='value'" v-model="values[f.key]" type="number" min="1" :step="f.key==='web_max_tabs'?1:'any'" :disabled="busy||!!submitted" :aria-label="f.label+' · '+f.unit" class="max-w-32"/></div><p v-if="policy" class="text-xs text-muted-foreground">Сохранённое эффективное значение: {{policy.effective[f.key]??'без ограничения'}} {{policy.effective[f.key]===null?'':f.unit}} · {{policy.sources[f.key]==='node'?'нода':policy.sources[f.key]==='server'?'сервер':'по умолчанию'}}</p></div>
<div v-if="submitted&&error" class="space-y-2 text-sm"><p>Сохранённая команда доступна для точного повтора. Для изменения параметров сначала получите текущее состояние сервера.</p><Button type="button" variant="outline" :disabled="busy" @click="load">Получить текущее состояние</Button></div>
<p class="text-xs text-muted-foreground">Действующие процессы сохраняются. Новые правила применяются при следующем обновлении размещения MCP.</p>
</EditorDialog></template>
