<script setup lang="ts">
import type {GitPolicy} from '../../model/connection-draft'
import {Input} from '@/shared/ui/input'
import {Switch} from '@/shared/ui/switch'
import { useId } from 'vue'
const model=defineModel<GitPolicy>({required:true})
const fieldId = useId()
defineProps<{provider:string;disabled:boolean}>()
function list(key:'protected_branches'|'required_checks'|'required_reviewers',event:Event): void {
  const target = event.target
  if (!(target instanceof HTMLInputElement)) return
  model.value = { ...model.value, [key]: target.value.split(',').map(value => value.trim()).filter(Boolean) }
}
</script>
<template><fieldset :disabled="disabled" class="space-y-3 rounded-lg border p-3"><legend class="px-1 text-sm font-medium">Политика Git</legend>
<label :for="`${fieldId}-branches`" class="block space-y-1 text-sm">Дополнительно защищённые ветки<Input :id="`${fieldId}-branches`" :model-value="model.protected_branches.join(', ')" maxlength="8192" placeholder="Например, release, production" @input="list('protected_branches',$event)"/></label>
<p class="text-xs text-muted-foreground">Ограничения самого GitHub/GitLab действуют всегда. Названия main и master сами по себе не запрещают запись.</p>
<template v-if="provider==='github'"><label :for="`${fieldId}-checks`" class="block space-y-1 text-sm">Проверки перед merge<Input :id="`${fieldId}-checks`" :model-value="model.required_checks?.join(', ')" maxlength="8192" @input="list('required_checks',$event)"/></label><label :for="`${fieldId}-reviewers`" class="block space-y-1 text-sm">Обязательные reviewer<Input :id="`${fieldId}-reviewers`" :model-value="model.required_reviewers?.join(', ')" maxlength="8192" @input="list('required_reviewers',$event)"/></label></template>
<label :for="`${fieldId}-local-first`" class="flex items-center justify-between gap-3 text-sm">Подсказки local-first<Switch :id="`${fieldId}-local-first`" v-model="model.local_first_guidance" :disabled="disabled"/></label>
<label :for="`${fieldId}-transport`" class="flex items-center justify-between gap-3 text-sm">Авторизованный локальный Git<Switch :id="`${fieldId}-transport`" v-model="model.local_git_transport_enabled" :disabled="disabled"/></label>
<label :for="`${fieldId}-mutations`" class="flex items-center justify-between gap-3 text-sm">Изменение исходников через API<Switch :id="`${fieldId}-mutations`" v-model="model.remote_source_mutations_enabled" :disabled="disabled"/></label>
<p class="text-xs text-muted-foreground">По умолчанию изменения выполняются локально и публикуются через Git. Последний переключатель разрешает прямые изменения файлов и истории через MCP; issue, комментарии и PR/MR от него не зависят.</p>
</fieldset></template>
