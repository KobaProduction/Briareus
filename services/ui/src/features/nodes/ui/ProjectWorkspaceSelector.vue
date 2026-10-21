<script setup lang="ts">
import {computed} from 'vue'
import type {ProjectWorkspace,ProjectWorkspaceMount} from '../model/project-workspace'
import {Select,SelectContent,SelectItem,SelectTrigger,SelectValue} from '@/shared/ui/select'
import {Switch} from '@/shared/ui/switch'
import {Button} from '@/shared/ui/button'
const props=defineProps<{workspaces:ProjectWorkspace[];busy?:boolean;error?:string;readOnlyRequired?:boolean}>()
const model=defineModel<ProjectWorkspaceMount|null>({required:true})
const emit=defineEmits<{create:[]}>()
const selection=computed({get:()=>model.value?.id??'none',set:(id:string)=>{model.value=id==='none'?null:{id,read_only:props.readOnlyRequired||model.value?.read_only||false}}})
const readOnly=computed({get:()=>props.readOnlyRequired||model.value?.read_only||false,set:(read_only:boolean)=>{if(model.value)model.value={...model.value,read_only}}})
</script>
<template>
 <fieldset class="space-y-2 border-t pt-3"><legend class="text-sm font-medium">Обмен файлами с проектом</legend>
  <Select v-model="selection" :disabled="busy"><SelectTrigger aria-label="Рабочая папка проекта"><SelectValue placeholder="Без общей папки"/></SelectTrigger><SelectContent><SelectItem value="none">Без общей папки</SelectItem><SelectItem v-for="workspace in workspaces" :key="workspace.id" :value="workspace.id">Папка проекта · {{workspace.id.slice(0,8)}}</SelectItem></SelectContent></Select>
  <label v-if="model" class="flex items-center justify-between gap-3 text-sm"><span>Только чтение</span><Switch v-model="readOnly" :disabled="busy||readOnlyRequired"/></label>
  <Button v-if="!workspaces.length" variant="outline" size="sm" type="button" :disabled="busy" @click="emit('create')">Создать папку проекта</Button>
  <p class="text-xs text-muted-foreground">{{readOnlyRequired?'Анализ читает файлы проекта без права их изменения. Результаты движков хранятся отдельно.':'Загрузки и отправка файлов доступны через общую папку проекта. Профиль и cookies браузера хранятся отдельно.'}} Модуль Files необязателен.</p>
  <p v-if="props.error" role="alert" class="text-xs text-destructive">{{props.error}}</p>
 </fieldset>
</template>
