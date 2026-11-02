<script setup lang="ts">
import {computed,ref,watch} from "vue"
import type {PlatformPerson} from "@/entities/user"
import {DataTable,type DataTableColumn} from "@/shared/ui/data-table"
import {Badge} from "@/shared/ui/badge"
import {Button} from "@/shared/ui/button"
import ConfirmationDialog from "@/shared/ui/ConfirmationDialog.vue"
const props=defineProps<{teamId:string;memberIds:string[];ownerId:string;users:PlatformPerson[];disabled:boolean;readOnly?:boolean}>()
const emit=defineEmits<{remove:[id:string]}>()
const rows=computed(()=>props.memberIds.map(id=>{const user=props.users.find(user=>user.id===id);return {id,name:user?.name||user?.email||'Пользователь',email:user?.email||'—',role:id===props.ownerId?'Владелец':'Участник'}}))
const allColumns:DataTableColumn<keyof (typeof rows.value)[number]>[]=[{key:'name',title:'Участник',dataIndex:'name'},{key:'email',title:'Email',dataIndex:'email'},{key:'role',title:'Роль в команде',dataIndex:'role'},{key:'actions',title:'',sortable:false}]
const columns=computed(()=>allColumns.filter(column=>column.key!=='actions'||!props.readOnly))
const removing=ref<string|null>(null)
const target=computed(()=>rows.value.find(row=>row.id===removing.value))
watch(()=>[props.memberIds,props.ownerId],()=>{if(removing.value&&(!target.value||removing.value===props.ownerId))removing.value=null})
watch(()=>props.teamId,()=>{removing.value=null})
function confirmRemove(){if(target.value&&!props.disabled&&target.value.id!==props.ownerId){emit('remove',target.value.id);removing.value=null}}
</script>
<template><DataTable :columns="columns" :rows="rows" label="Участники команды"><template #cell="{row,column}"><span v-if="column.key==='name'" class="font-medium" :title="row.id">{{row.name}}</span><span v-else-if="column.key==='email'" class="text-muted-foreground">{{row.email}}</span><Badge v-else-if="column.key==='role'" variant="outline">{{row.role}}</Badge><Button v-else-if="row.id!==ownerId" variant="ghost" size="sm" :disabled="disabled" @click="removing=row.id">Удалить из команды</Button></template></DataTable><ConfirmationDialog :open="!!target" title="Удалить участника из команды?" :description="`${target?.name||'Пользователь'} потеряет доступ через эту команду. Учётная запись останется в системе.`" confirm-label="Удалить из команды" :busy="disabled" @update:open="value=>{if(!value)removing=null}" @confirm="confirmRemove"/></template>
