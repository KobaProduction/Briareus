<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { Activity, LockKeyhole } from "lucide-vue-next"
import { Card,CardContent,CardHeader,CardTitle } from "@/shared/ui/card"
const {locale}=useI18n()
const title=computed(()=>locale.value==="ru"?"Инфраструктура":"Infrastructure")
const sources=computed(()=>locale.value==="ru"?[
  {name:"Наблюдаемость",provider:"SigNoz",description:"Метрики, журналы и трассировки сервисов"},
  {name:"Развёртывание и управление",provider:"Coolify",description:"Приложения, развёртывание и состояние системы"},
]:[
  {name:"Observability",provider:"SigNoz",description:"Service metrics, logs and traces"},
  {name:"Deployment and management",provider:"Coolify",description:"Applications, deployments and system status"},
])
const notice=computed(()=>locale.value==="ru"?
  "Для просмотра метрик, трассировок и логов нужен разрешённый Control Panel API. Состояние сервисов здесь не подменяется тестовыми данными.":
  "Metrics, traces and logs require an authorized Control Panel API. Service status is not simulated.")
</script>
<template>
  <Card>
    <CardHeader><CardTitle class="flex items-center gap-2 text-sm"><Activity class="size-4"/>{{title}}</CardTitle></CardHeader>
    <CardContent class="space-y-3">
      <div v-for="source in sources" :key="source.provider" class="flex min-h-16 items-center gap-3 rounded-lg border border-border px-3 py-2">
        <div class="flex-1"><p class="text-sm font-medium">{{source.name}} · {{source.provider}}</p>
          <p class="text-xs text-muted-foreground">{{source.description}}</p></div><LockKeyhole class="size-4 text-muted-foreground" aria-hidden="true"/>
      </div>
      <p role="status" class="text-xs leading-5 text-muted-foreground">{{notice}}</p>
    </CardContent>
  </Card>
</template>
