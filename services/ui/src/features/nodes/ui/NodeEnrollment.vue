<script setup lang="ts">
import {useId} from "vue"
import {Textarea} from '@/shared/ui/textarea'
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription} from '@/shared/ui/dialog'
import EditorDialog from '@/shared/ui/EditorDialog.vue'
import {nodeGateway} from "../api/nodes"
import {useNodeEnrollment} from "../model/use-node-enrollment"
import type {ManagedNode} from "@/entities/node"
const formId=useId()
const props=defineProps<{node:ManagedNode;projectId:string;action:'setup'|'pair'|'enable'}>()
const emit=defineEmits<{changed:[];close:[]}>()
const {busy,error,publicKey,setup,pair,enable}=useNodeEnrollment(props,nodeGateway, {changed:()=>emit("changed"),close:()=>emit("close")})
</script>
<template>
  <Dialog v-if="action==='setup'" :open="true" @update:open="value=>{if(!value)emit('close')}"><DialogContent class="max-w-xl"><DialogHeader><DialogTitle>Установка: {{node.name}}</DialogTitle><DialogDescription>Публичные параметры для выделенного runtime. Установка на сервер и bootstrap выполняются отдельно; эта форма не запускает контейнеры.</DialogDescription></DialogHeader><p v-if="busy" class="text-sm text-muted-foreground">Получаем параметры…</p><p v-if="error" role="alert" class="text-sm text-destructive">{{error}}</p><pre v-if="setup" class="max-h-80 overflow-auto rounded bg-muted p-3 text-xs">{{setup}}</pre><p class="text-sm text-muted-foreground">После запуска получите публичный ключ внутри контроллера командой <code>python -m node_agent.identity</code> и укажите его в «Подключить ноду». Приватный ключ остаётся на ноде.</p></DialogContent></Dialog>
  <EditorDialog v-else :open="true" :title="action==='pair'?'Подтвердить identity ноды':'Включить ноду'" :description="action==='pair'?'Вставьте публичный Ed25519-ключ из доверенного канала установки. Core проверит подписанный ответ работающей ноды, прежде чем сохранить ключ.':'Core отправит подписанную настройку выбранной ноде. Это разрешает управление её MCP; права пользователей проверяются отдельно.'" :submit-label="action==='pair'?'Проверить и подключить':'Включить'" :busy="busy" :disabled="action==='pair'&&!publicKey.trim()" :error="error" @update:open="value=>{if(!value)emit('close')}" @submit="action==='pair'?pair():enable()"><label :for="`${formId}-key`" v-if="action==='pair'" class="block space-y-2 text-sm">Публичный ключ PEM<Textarea :id="`${formId}-key`" v-model="publicKey" rows="4" maxlength="256" placeholder="-----BEGIN PUBLIC KEY-----"/></label></EditorDialog>
</template>
