<script setup lang="ts">
import {computed} from 'vue'
import {Button} from '@/shared/ui/button'
import RowActions from '@/shared/ui/RowActions.vue'
import StatusBadge from '@/shared/ui/StatusBadge.vue'
import PlacementStatusDetails from './PlacementStatusDetails.vue'
import {operationStatus,operationInProgress,operationError,type PlacementOperation} from '../model/operation-presentation'
const props=defineProps<{operation:PlacementOperation|null;state:string;module:string;name:string;busy:boolean;recovering?:boolean}>()
const emit=defineEmits<{edit:[];reconcile:[];recover:[]}>()
const status=computed(()=>props.recovering?{label:'Сверяем состояние',tone:'info' as const}:operationStatus(props.operation))
const active=computed(()=>operationInProgress(props.operation))
const failure=computed(()=>operationError(props.operation))
const canEdit=computed(()=>!active.value&&(props.state==='ready'||props.state==='failed')&&!props.operation?.reconciliation_required)
const actionLabel=computed(()=>props.state==='failed'?'Настроить повторный запуск':['web','serena'].includes(props.module)?'Настройки':'Обновить сборку')
</script>
<template>
 <div class="min-w-0 max-w-64 space-y-1">
  <div class="flex items-center justify-between gap-1">
   <PlacementStatusDetails v-if="operation" :operation="operation" :state="state" :name="name">
    <Button type="button" variant="ghost" size="xs" class="h-auto min-w-0 justify-start whitespace-normal p-0 text-left hover:bg-transparent" :aria-label="status.label+'. Сведения об операции: '+name" :aria-busy="active||recovering"><StatusBadge :label="status.label" :tone="status.tone" :busy="active||recovering" wrap/></Button>
   </PlacementStatusDetails>
   <StatusBadge v-else :label="status.label" :tone="status.tone"/>
   <div class="flex shrink-0 items-center gap-0.5">
    <RowActions v-if="operation?.reconciliation_required||canEdit" :label="'Действия с MCP '+name" :disabled="busy">
     <Button v-if="operation?.reconciliation_required" type="button" variant="ghost" size="sm" class="w-full justify-start" :disabled="busy" @click="emit('reconcile')">Сверить с нодой</Button>
     <Button v-if="canEdit" type="button" variant="ghost" size="sm" class="h-auto w-full justify-start whitespace-normal py-2 text-left" :disabled="busy||active" @click="emit('recover')">Запустить сохранённую конфигурацию</Button>
     <Button v-if="canEdit" type="button" variant="ghost" size="sm" class="h-auto w-full justify-start whitespace-normal py-2 text-left" :disabled="busy||active" @click="emit('edit')">{{actionLabel}}</Button>
    </RowActions>
   </div>
  </div>
  <p v-if="failure" class="max-w-64 text-xs leading-4 text-destructive">{{failure}}</p>
 </div>
</template>
