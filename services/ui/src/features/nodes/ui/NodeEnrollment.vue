<script setup lang="ts">
import {onMounted,ref} from 'vue'
import type {ManagedNode} from '@/entities/node/model/types'
import {nodeCommand} from '../api/nodes'
import {Textarea} from '@/shared/ui/textarea'
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription} from '@/shared/ui/dialog'
import EditorDialog from '@/shared/ui/EditorDialog.vue'

const props=defineProps<{node:ManagedNode;projectId:string;action:'setup'|'pair'|'enable'}>()
const emit=defineEmits<{changed:[];close:[]}>()
const busy=ref(false),error=ref(''),publicKey=ref(''),setup=ref('')
let operation=crypto.randomUUID()
function command(action:string){return {operation_uuid:operation,action,node_uuid:props.node.id,expected_sequence:props.node.sequence}}
async function showSetup(){
  if(busy.value)return
  busy.value=true;error.value='';operation=crypto.randomUUID()
  try{const result=await nodeCommand<{setup:Record<string,unknown>}>(props.projectId,command('setup'));setup.value=JSON.stringify(result.setup,null,2)}
  catch{error.value='Не удалось получить параметры установки.'}
  finally{busy.value=false}
}
async function pair(){
  if(busy.value)return
  busy.value=true;error.value=''
  try{await nodeCommand(props.projectId,{...command('pair'),public_key:publicKey.value.trim()+'\n'});emit('changed');emit('close')}
  catch{error.value='Подключение не подтверждено. Проверьте публичный ключ, адрес и разрешение адреса в Core. Изменённые параметры требуют новой операции.'}
  finally{busy.value=false}
}
async function enable(){
  if(busy.value)return
  busy.value=true;error.value='';operation=crypto.randomUUID()
  try{await nodeCommand(props.projectId,command('enable'));emit('changed');emit('close')}
  catch{error.value='Включение не подтверждено. Проверьте состояние ноды перед повторной командой.'}
  finally{busy.value=false}
}
onMounted(()=>{if(props.action==='setup')void showSetup()})
</script>
<template>
  <Dialog v-if="action==='setup'" :open="true" @update:open="value=>{if(!value)emit('close')}"><DialogContent class="max-w-xl"><DialogHeader><DialogTitle>Установка: {{node.name}}</DialogTitle><DialogDescription>Публичные параметры для выделенного runtime. Установка на сервер и bootstrap выполняются отдельно; эта форма не запускает контейнеры.</DialogDescription></DialogHeader><p v-if="busy" class="text-sm text-muted-foreground">Получаем параметры…</p><p v-if="error" role="alert" class="text-sm text-destructive">{{error}}</p><pre v-if="setup" class="max-h-80 overflow-auto rounded bg-muted p-3 text-xs">{{setup}}</pre><p class="text-sm text-muted-foreground">После запуска получите публичный ключ внутри контроллера командой <code>python -m node_agent.identity</code> и укажите его в «Подключить ноду». Приватный ключ остаётся на ноде.</p></DialogContent></Dialog>
  <EditorDialog v-else :open="true" :title="action==='pair'?'Подтвердить identity ноды':'Включить ноду'" :description="action==='pair'?'Вставьте публичный Ed25519-ключ из доверенного канала установки. Core проверит подписанный ответ работающей ноды, прежде чем сохранить ключ.':'Core отправит подписанную настройку выбранной ноде. Это разрешает управление её MCP; права пользователей проверяются отдельно.'" :submit-label="action==='pair'?'Проверить и подключить':'Включить'" :busy="busy" :disabled="action==='pair'&&!publicKey.trim()" :error="error" @update:open="value=>{if(!value)emit('close')}" @submit="action==='pair'?pair():enable()"><label v-if="action==='pair'" class="block space-y-2 text-sm">Публичный ключ PEM<Textarea v-model="publicKey" rows="4" maxlength="256" placeholder="-----BEGIN PUBLIC KEY-----"/></label></EditorDialog>
</template>
