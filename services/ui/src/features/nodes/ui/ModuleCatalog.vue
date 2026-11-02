<script setup lang="ts">
import {useId} from "vue"
import ModuleComponentsDialog from './ModuleComponentsDialog.vue'
import {DataTable} from "@/shared/ui/data-table"
import EditorDialog from '@/shared/ui/EditorDialog.vue'
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription} from '@/shared/ui/dialog'
import {Button} from '@/shared/ui/button'
import {Input} from '@/shared/ui/input'
import {Badge} from '@/shared/ui/badge'
import {nodeGateway} from "../api/nodes"
import {useModuleCatalog} from "../model/use-module-catalog"
import {placementStateSummary} from "../model/module-presentation"
const formId=useId()
const props=defineProps<{projectId:string}>()
const emit=defineEmits<{close:[]}>()
const {releases,loading,error,placements,details,publication,busy,formError,commit,fingerprint,image,rows,availability,imageCount,valid,open,openComponent,publish}=useModuleCatalog(props,nodeGateway)
</script>
<template>
 <Dialog :open="true" @update:open="value=>{if(!value&&!busy)emit('close')}"><DialogContent class="min-w-0 w-[calc(100vw-2rem)] max-w-[calc(100vw-2rem)] max-h-[90vh] overflow-y-auto sm:max-w-4xl [&>*]:min-w-0 [&>*]:max-w-full"><DialogHeader class="min-w-0 max-w-full"><DialogTitle>Образы MCP</DialogTitle><DialogDescription class="whitespace-normal break-words">Независимые компоненты ноды и одобренные неизменяемые сборки. Публикация образа сама по себе не запускает MCP. Состояние конкретного контейнера показывается в размещениях проекта.</DialogDescription></DialogHeader>
 <p v-if="error" role="alert" class="text-sm text-destructive">{{error}}</p>
 <DataTable class="min-w-0 max-w-full" :rows="rows" :loading="loading" label="Каталог MCP" :search-text="row=>row.name+' '+row.components.map(item=>item.name).join(' ')" selectable @select="row=>details=row" :columns="[{key:'name',title:'Модуль',dataIndex:'name'},{key:'state',title:'Адаптер'},{key:'images',title:'Образы'},{key:'runtime',title:'В проекте'},{key:'actions',title:'Действия'}]">
  <template #cell="{row,column}"><span v-if="column.key==='name'" class="whitespace-nowrap">{{row.name}}</span><Badge v-else-if="column.key==='state'" variant="outline" class="whitespace-nowrap">{{availability(row)}}</Badge><Button v-else-if="column.key==='images'" variant="ghost" size="sm" class="h-7 whitespace-nowrap px-1" @click="details=row">{{imageCount(row)}} опубликовано</Button><span v-else-if="column.key==='runtime'" class="whitespace-nowrap">{{placementStateSummary(placements,row.modules)}}</span><Button v-else-if="column.key==='actions'&&row.id!=='development'&&row.components.length===1&&row.components[0]?.node_adapter" size="sm" variant="outline" @click="openComponent(row.components[0])">Опубликовать</Button><Button v-else-if="column.key==='actions'" size="sm" variant="outline" @click="details=row">{{row.id==='development'?'Компоненты':'Подробнее'}}</Button></template>
 </DataTable>
 </DialogContent></Dialog>
 <ModuleComponentsDialog :open="!!details" :single="details?.id!=='development'" :title="details?.name??''" :components="details?.components??[]" :releases="releases" :placements="placements" @close="details=null" @publish="open"/>
 <EditorDialog :open="!!publication" :title="'Публикация: '+(publication?.name??'')" description="Укажите существующий образ из разрешённого registry и данные его сборки. Идентификатор digest закрепляется и не изменяется после публикации." :busy="busy" :disabled="!valid" :error="formError" submit-label="Опубликовать" @update:open="value=>{if(!value)publication=null}" @submit="publish">
  <label :for="`${formId}-image`" class="block space-y-1 text-sm">Образ с digest<Input :id="`${formId}-image`" v-model="image" maxlength="512" placeholder="registry/repository@sha256:…"/></label>
  <label :for="`${formId}-commit`" class="block space-y-1 text-sm">Коммит исходников<Input :id="`${formId}-commit`" v-model="commit" maxlength="40"/></label>
  <label :for="`${formId}-fingerprint`" class="block space-y-1 text-sm">SHA256 входных файлов сборки<Input :id="`${formId}-fingerprint`" v-model="fingerprint" maxlength="64"/></label>
  <p class="text-xs text-muted-foreground">{{publication?.inputs.platform}} · {{publication?.inputs.dockerfile}}</p>
 </EditorDialog>
</template>
