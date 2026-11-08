<script setup lang="ts">
import { useI18n } from "vue-i18n"
const { t } = useI18n()
</script>
<template>
  <section class="space-y-3 text-sm">
    <h2 class="font-medium">{{ t("services.serenaProjects") }}</h2>
    <p class="text-muted-foreground">{{ t("services.serenaWorkspaceHint") }}</p>
    <p class="text-muted-foreground">{{ t("services.serenaIsolationHint") }}</p>
  </section>
</template>
