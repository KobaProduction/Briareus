<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { useServiceCatalog } from "@/shared/services/store"
import Button from "@/shared/ui/Button.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"
const props = defineProps<{ serviceId?: string }>()
const { t } = useI18n()
const catalog = useServiceCatalog()
const service = computed(() => props.serviceId ? catalog.service(props.serviceId) : undefined)
function connect(): void { location.hash = "connections" }
</script>
<template>
  <div class="space-y-5">
    <PageHeader :title="service?.name ?? t('services.title')" :description="t('services.genericHint')" />
    <Button variant="outline" @click="connect">{{ t("services.connections") }}</Button>
  </div>
</template>
