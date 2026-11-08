<script setup lang="ts">
import { computed } from "vue"
import { Activity, Blocks, Cable, Settings } from "lucide-vue-next"
import { useI18n } from "vue-i18n"
import { useServiceCatalog } from "@/shared/services/store"
import { serviceForRoute, servicePath } from "@/shared/services/catalog"
const props = defineProps<{ collapsed: boolean; activePath: string }>()
const { t, te } = useI18n()
const catalog = useServiceCatalog()
const currentService = computed(() => serviceForRoute(props.activePath))
const core = computed(() => [
  { path: "dashboard", label: t("nav.dashboard"), icon: Activity },
  { path: "services", label: t("services.title"), icon: Cable },
  { path: "calls", label: t("nav.calls"), icon: Blocks },
  { path: "settings/interface", label: t("nav.settings"), icon: Settings },
])
function groupLabel(id: string): string {
  return te(`services.groups.${id}`) ? t(`services.groups.${id}`) : id
}
function navigate(path: string): void {
  location.hash = path
}
</script>
<template>
  <nav class="space-y-4" :aria-label="t('services.navigation')">
    <div class="space-y-1">
      <button
        v-for="item in core"
        :key="item.path"
        class="flex h-9 w-full items-center gap-3 rounded-md px-3 text-left text-sm transition"
        :class="
          activePath.split('/')[0] === item.path.split('/')[0] &&
          !currentService
            ? 'bg-accent text-foreground'
            : 'text-muted-foreground hover:bg-accent hover:text-foreground'
        "
        :title="collapsed ? item.label : undefined"
        @click="navigate(item.path)"
      >
        <component :is="item.icon" class="size-4 shrink-0" /><span
          v-if="!collapsed"
          >{{ item.label }}</span
        >
      </button>
    </div>
    <label
      class="flex items-center gap-2 px-3 text-xs text-muted-foreground"
      :title="t('services.showUnavailable')"
      ><input v-model="catalog.showUnavailable" type="checkbox" /><span
        v-if="!collapsed"
        >{{ t("services.showUnavailable") }}</span
      ></label
    >
    <section v-for="group in catalog.groups" :key="group.id" class="space-y-1">
      <h2
        v-if="!collapsed"
        class="px-3 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground"
      >
        {{ groupLabel(group.id) }}
      </h2>
      <template v-for="service in group.services" :key="service.id"
        ><button
          class="flex min-h-9 w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition disabled:cursor-not-allowed disabled:opacity-45"
          :class="
            currentService === service.id
              ? 'bg-accent text-foreground'
              : 'text-muted-foreground hover:bg-accent hover:text-foreground'
          "
          :disabled="!service.connected"
          :title="
            service.name +
            (!service.connected ? ' · ' + t('common.disconnected') : '')
          "
          @click="navigate(servicePath(service.id))"
        >
          <Cable class="size-4 shrink-0" /><span
            v-if="!collapsed"
            class="truncate"
            >{{ service.name }}</span
          ><span
            v-if="!collapsed && !service.connected"
            class="ml-auto text-[10px]"
            >{{ t("common.disconnected") }}</span
          >
        </button>
        <div
          v-if="service.id === 'server' && service.connected && !collapsed"
          class="ml-5 space-y-0.5 border-l border-border pl-2"
        >
          <button
            v-for="child in [
              { path: 'server/files', label: t('nav.files') },
              { path: 'server/terminal', label: t('nav.terminal') },
            ]"
            :key="child.path"
            class="block w-full rounded-md px-3 py-1.5 text-left text-xs"
            :class="
              activePath === child.path
                ? 'bg-background font-medium'
                : 'text-muted-foreground hover:bg-accent'
            "
            @click="navigate(child.path)"
          >
            {{ child.label }}
          </button>
        </div></template
      >
    </section>
  </nav>
</template>
