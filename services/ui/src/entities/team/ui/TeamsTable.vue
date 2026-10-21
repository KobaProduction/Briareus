<script setup lang="ts">
import {computed} from "vue"
import type {ManagedTeam} from "../model/types"
import DataTable from "@/shared/ui/data-table/DataTable.vue"
import {Button} from "@/shared/ui/button"
const props=defineProps<{teams:ManagedTeam[];ownerNames:Record<string,string>;selectedId:string;loading?:boolean}>()
const emit=defineEmits<{select:[id:string]}>()
const rows=computed(()=>props.teams.map(team=>({...team,ownerName:props.ownerNames[team.owner_user_id]||'Пользователь',memberCount:team.member_ids.length})))
const columns=[{key:'name',title:'Команда',dataIndex:'name'},{key:'ownerName',title:'Владелец',dataIndex:'ownerName'},{key:'memberCount',title:'Участники',dataIndex:'memberCount'}]
</script>
<template><DataTable :columns="columns" :rows="rows" :loading="loading" label="Команды"><template #cell="{row,column}"><Button v-if="column.key==='name'" variant="ghost" size="sm" class="-ml-3 justify-start" :aria-pressed="selectedId===row.id" @click="emit('select',row.id)">{{row.name}}</Button><span v-else-if="column.key==='ownerName'">{{row.ownerName}}</span><span v-else class="tabular-nums">{{row.memberCount}}</span></template></DataTable></template>
