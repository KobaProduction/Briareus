<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { computed } from "vue"
import ServiceCatalog from "@/features/mcp-services/ServiceCatalog.vue"
const props = defineProps<{ serviceId?: string }>()
const { t } = useI18n()
const selected = computed(() => props.serviceId)
</script>
<template>
  <div class="space-y-6">
    <p v-if="selected" class="text-sm text-muted-foreground">
      {{ t("services.genericHint") }}
    </p>
    <ServiceCatalog />
  </div>
</template>
