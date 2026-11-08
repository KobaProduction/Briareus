<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { useServiceCatalog } from "@/shared/services/store"
import { servicePath, serviceConnectionUrl } from "@/shared/services/catalog"
import Button from "@/shared/ui/Button.vue"
const { t, te } = useI18n()
const catalog = useServiceCatalog()
const origin = location.origin
function groupLabel(id: string): string {
  return te(`services.groups.${id}`) ? t(`services.groups.${id}`) : id
}
function open(id: string): void {
  if (catalog.connected(id)) location.hash = servicePath(id)
}
</script>
<template>
  <section class="space-y-4" aria-labelledby="mcp-services-heading">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 id="mcp-services-heading" class="text-lg font-semibold">
          {{ t("services.title") }}
        </h2>
        <p class="text-sm text-muted-foreground">
          {{ t("services.description") }}
        </p>
      </div>
      <div class="flex items-center gap-3">
        <label class="flex items-center gap-2 text-xs"
          ><input v-model="catalog.showUnavailable" type="checkbox" />{{
            t("services.showUnavailable")
          }}</label
        ><Button
          variant="outline"
          size="sm"
          :disabled="catalog.loading"
          @click="catalog.refresh"
          >{{ t("common.refresh") }}</Button
        >
      </div>
    </div>
    <p
      v-if="catalog.error"
      role="status"
      class="text-sm text-amber-700 dark:text-amber-300"
    >
      {{ t("services.discoveryUnavailable") }}
    </p>
    <p
      v-if="!catalog.groups.length"
      class="rounded-lg border border-border p-5 text-sm text-muted-foreground"
    >
      {{ t("services.empty") }}
    </p>
    <div v-for="group in catalog.groups" :key="group.id" class="space-y-2">
      <h3
        class="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
      >
        {{ groupLabel(group.id) }}
      </h3>
      <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <article
          v-for="service in group.services"
          :key="service.id"
          class="rounded-xl border border-border bg-card p-4"
          :class="!service.connected && 'opacity-60'"
        >
          <div class="flex items-start justify-between gap-3">
            <h4 class="font-medium">{{ service.name }}</h4>
            <span
              class="text-xs"
              :class="
                service.connected ? 'text-emerald-600' : 'text-muted-foreground'
              "
              >{{
                t(
                  service.connected
                    ? "common.connected"
                    : "common.disconnected",
                )
              }}</span
            >
          </div>
          <p class="mt-2 break-all font-mono text-xs text-muted-foreground">
            {{ serviceConnectionUrl(service.mcp_path, origin) || "—" }}
          </p>
          <Button
            class="mt-4"
            variant="outline"
            size="sm"
            :disabled="!service.connected"
            @click="open(service.id)"
            >{{ t("common.open") }}</Button
          >
        </article>
      </div>
    </div>
  </section>
</template>
