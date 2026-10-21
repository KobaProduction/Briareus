<script setup lang="ts">
import type {VerifiedPlatformContext} from '@/entities/workspace/model/proof'
import DataTable from '@/shared/ui/data-table/DataTable.vue'
defineProps<{context:VerifiedPlatformContext}>()
</script>
<template><section class="space-y-4"><div><h2 class="text-lg font-semibold">Авторизация · Rauthy</h2><p class="mt-1 text-sm text-muted-foreground">Общий внешний сервер идентификации. Права на действия проверяет Authorization с Cedar.</p></div><DataTable :rows="[{id:'identity',component:'Rauthy',purpose:'Учётные записи, вход, MFA и токены',state:'Личность подтверждена текущим сеансом'},{id:'policy',component:'Authorization / Cedar',purpose:'Права проектов и сеансов агентов',state:'Проверяется для каждой операции'}]" :columns="[{key:'component',title:'Сервис',dataIndex:'component'},{key:'purpose',title:'Назначение',dataIndex:'purpose'},{key:'state',title:'Подтверждение',dataIndex:'state'}]" label="Сервисы авторизации"/><p class="break-all text-xs text-muted-foreground">Издатель текущей личности: {{context.rauthy.issuer}}</p></section></template>
