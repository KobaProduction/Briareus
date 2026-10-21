<script setup lang="ts">
import type {GitPolicy} from '../../model/connection-draft'
import {Input} from '@/shared/ui/input'
import {Switch} from '@/shared/ui/switch'
const model=defineModel<GitPolicy>({required:true})
defineProps<{provider:string;disabled:boolean}>()
function list(key:'protected_branches'|'required_checks'|'required_reviewers',event:Event){model.value={...model.value,[key]:(event.target as HTMLInputElement).value.split(',').map(s=>s.trim()).filter(Boolean)}}
</script>
<template><fieldset :disabled="disabled" class="space-y-3 rounded-lg border p-3"><legend class="px-1 text-sm font-medium">Политика Git</legend>
<label class="block space-y-1 text-sm">Дополнительно защищённые ветки<Input :model-value="model.protected_branches.join(', ')" maxlength="8192" placeholder="Например, release, production" @input="list('protected_branches',$event)"/></label>
<p class="text-xs text-muted-foreground">Ограничения самого GitHub/GitLab действуют всегда. Названия main и master сами по себе не запрещают запись.</p>
<template v-if="provider==='github'"><label class="block space-y-1 text-sm">Проверки перед merge<Input :model-value="model.required_checks?.join(', ')" maxlength="8192" @input="list('required_checks',$event)"/></label><label class="block space-y-1 text-sm">Обязательные reviewer<Input :model-value="model.required_reviewers?.join(', ')" maxlength="8192" @input="list('required_reviewers',$event)"/></label></template>
<label class="flex items-center justify-between gap-3 text-sm">Подсказки local-first<Switch v-model="model.local_first_guidance" :disabled="disabled"/></label>
<label class="flex items-center justify-between gap-3 text-sm">Авторизованный локальный Git<Switch v-model="model.local_git_transport_enabled" :disabled="disabled"/></label>
<label class="flex items-center justify-between gap-3 text-sm">Изменение исходников через API<Switch v-model="model.remote_source_mutations_enabled" :disabled="disabled"/></label>
<p class="text-xs text-muted-foreground">По умолчанию изменения выполняются локально и публикуются через Git. Последний переключатель разрешает прямые изменения файлов и истории через MCP; issue, комментарии и PR/MR от него не зависят.</p>
</fieldset></template>
