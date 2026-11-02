<script setup lang="ts">
// Compact indicator from HTTP Bridge; diagnostics live in the Events section.
import {computed} from "vue"
import {LoaderCircle,PlugZap,Unplug} from "lucide-vue-next"
import {eventBus} from "@/shared/events"
const live=computed(()=>eventBus.state.status==='connected')
const connecting=computed(()=>['connecting','reconnecting'].includes(eventBus.state.status))
const label=computed(()=>live.value?'Соединение установлено':connecting.value?'Переподключение…':'Нет соединения')
</script>
<template>
  <a href="#platform/events" class="inline-flex size-7 items-center justify-center rounded-md hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" :aria-label="label" :title="label"><PlugZap v-if="live" class="size-4 text-emerald-500"/><LoaderCircle v-else-if="connecting" class="size-4 animate-pulse text-amber-500"/><Unplug v-else class="size-4 text-rose-500"/></a>
</template>
