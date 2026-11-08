<script setup lang="ts">
import { useI18n } from "vue-i18n"
withDefaults(defineProps<{ rows?: number; columns?: number }>(), { rows: 4, columns: 3 })
const { t } = useI18n()
</script>
<template>
  <div role="status" :aria-label="t('common.loading')" aria-busy="true" class="space-y-3 p-4">
    <div v-for="row in rows" :key="row" aria-hidden="true" class="grid gap-4" :style="{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }">
      <div v-for="column in columns" :key="column" class="h-5 animate-pulse rounded-md bg-muted motion-reduce:animate-none" :class="row % 2 ? 'w-5/6' : 'w-2/3'" />
    </div>
  </div>
</template>
