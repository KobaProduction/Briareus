<script setup lang="ts">
import {computed} from 'vue'
import DetailHoverCard from '@/shared/ui/DetailHoverCard.vue'
import {presentInstant} from '@/shared/lib/event-time'
import {uiPreferences} from '@/shared/lib/preferences'
import {operationError,operationStatus,placementStatus,diagnosticCause,diagnosticFacts,type PlacementOperation} from '../model/operation-presentation'
const props=defineProps<{operation:PlacementOperation;state:string;name:string;sequence?:number}>()
const failure=computed(()=>operationError(props.operation))
const stateLabel=computed(()=>placementStatus(props.state,props.sequence??1).label)
const operationLabel=computed(()=>operationStatus(props.operation).label)
const cause=computed(()=>diagnosticCause(props.operation.diagnostic))
const facts=computed(()=>diagnosticFacts(props.operation.diagnostic))
const updated=computed(()=>presentInstant(props.operation.updated_at,uiPreferences.locale.value==='en'?'en':'ru',uiPreferences.displayTimeZone.value))
</script>
<template>
 <DetailHoverCard :label="'Сведения о MCP: '+name">
  <template #trigger><slot/></template>
  <p class="font-medium">{{name}}</p>
  <div v-if="failure" class="space-y-1"><p class="text-sm text-destructive">{{failure}}</p><p class="text-xs">{{cause}}</p></div>
  <dl class="max-h-64 space-y-2 overflow-y-auto text-xs">
   <div v-for="fact in facts" :key="fact.label"><dt class="text-muted-foreground">{{fact.label}}</dt><dd>{{fact.value}}</dd></div>
   <div><dt class="text-muted-foreground">Последнее изменение</dt><dd><time v-if="updated&&operation.updated_at" :datetime="operation.updated_at">{{updated}}</time><span v-else>Время не передано сервером</span></dd></div>
   <div><dt class="text-muted-foreground">Идентификатор операции</dt><dd class="break-all font-mono">{{operation.id}}</dd></div>
   <div><dt class="text-muted-foreground">Состояние размещения</dt><dd>{{stateLabel}}</dd></div>
   <div><dt class="text-muted-foreground">Состояние операции</dt><dd>{{operationLabel}}</dd></div>
   <div v-if="operation.error"><dt class="text-muted-foreground">Код ошибки</dt><dd class="break-all font-mono text-destructive">{{operation.error}}</dd></div>
   <div v-if="operation.reconciliation_required"><dt class="text-muted-foreground">Восстановление</dt><dd class="text-muted-foreground">Текущее состояние нужно подтвердить по журналу ноды. Сверка не запускает контейнер повторно.</dd></div>
  </dl>
 </DetailHoverCard>
</template>
