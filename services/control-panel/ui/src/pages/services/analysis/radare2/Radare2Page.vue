<script setup lang="ts">
import { useI18n } from "vue-i18n"
const { t } = useI18n()
</script>
<template>
  <section class="space-y-3 text-sm">
    <h2 class="font-medium">{{ t("services.radare2Title") }}</h2>
    <p class="text-muted-foreground">{{ t("services.radare2Hint") }}</p>
    <p class="text-muted-foreground">{{ t("services.genericHint") }}</p>
  </section>
</template>
