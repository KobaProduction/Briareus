<script setup lang="ts">
import type {PlatformPerson} from "../model/types"
import {DataTable,type DataTableColumn} from "@/shared/ui/data-table"
import {Badge} from "@/shared/ui/badge"
defineProps<{users:PlatformPerson[];loading?:boolean}>()
const columns:DataTableColumn<keyof PlatformPerson>[]=[{key:'name',title:'Имя',dataIndex:'name'},{key:'email',title:'Email',dataIndex:'email'},{key:'role',title:'Роль',dataIndex:'role'},{key:'enabled',title:'Статус',dataIndex:'enabled'}]
</script>
<template><DataTable :columns="columns" :rows="users" :loading="loading" label="Пользователи"><template #cell="{row,column}"><span v-if="column.key==='name'" class="font-medium" :title="row.id">{{row.name||row.email||'Пользователь'}}</span><span v-else-if="column.key==='email'" class="text-muted-foreground">{{row.email||'—'}}</span><Badge v-else-if="column.key==='role'" variant="outline">{{row.role==='operator'?'Администратор':'Пользователь'}}</Badge><Badge v-else variant="secondary">{{row.enabled?'Активен':'Отключён'}}</Badge></template></DataTable></template>
