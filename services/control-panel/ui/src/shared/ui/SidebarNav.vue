<script setup lang="ts">
import { computed } from "vue"
import { CollapsibleRoot, CollapsibleTrigger, CollapsibleContent } from "reka-ui"
import { Activity, Blocks, Cable, ChevronRight, GitBranch, Globe, Server, Settings, Eye, EyeOff } from "lucide-vue-next"
import { useI18n } from "vue-i18n"
import { useServiceCatalog } from "@/shared/services/store"
import { groupedServices, serviceForRoute, servicePath } from "@/shared/services/catalog"
const props = defineProps<{ collapsed: boolean; activePath: string }>()
const { t, te } = useI18n()
const catalog = useServiceCatalog()
const currentService = computed(() => serviceForRoute(props.activePath))
const groups = computed(() => groupedServices(catalog.services, catalog.showUnavailable))
const core = computed(() => [
  { path: "dashboard", label: t("nav.dashboard"), icon: Activity },
  { path: "connections", label: t("services.connections"), icon: Cable },
  { path: "calls", label: t("nav.calls"), icon: Blocks },
  { path: "settings/interface", label: t("nav.settings"), icon: Settings },
])
const groupIcons: Record<string, typeof Cable> = { svc: GitBranch, web: Globe, server: Server }
function groupLabel(id: string): string {
  return te(`services.groups.${id}`) ? t(`services.groups.${id}`) : id
}
function coreActive(path: string): boolean {
  const root = props.activePath.split("/")[0]
  return !currentService.value && (root === path.split("/")[0] || (root === "services" && path === "connections"))
}
function navigate(path: string): void { location.hash = path }
</script>
<template>
  <nav class="space-y-4" :aria-label="t('services.navigation')">
    <div class="space-y-1">
      <button v-for="item in core" :key="item.path"
        class="flex h-9 w-full items-center gap-3 rounded-md px-3 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        :class="coreActive(item.path) ? 'bg-accent text-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground'"
        :title="collapsed ? item.label : undefined" @click="navigate(item.path)">
        <component :is="item.icon" class="size-4 shrink-0" /><span v-if="!collapsed">{{ item.label }}</span>
      </button>
    </div>
    <button type="button" class="flex min-h-9 w-full items-center gap-3 rounded-md px-3 text-left text-xs text-muted-foreground hover:bg-accent" :aria-pressed="catalog.showUnavailable" :aria-label="t('services.showUnavailable')" :title="t('services.showUnavailable')" @click="catalog.showUnavailable = !catalog.showUnavailable">
      <component :is="catalog.showUnavailable ? EyeOff : Eye" class="size-4 shrink-0" /><span v-if="!collapsed">{{ t('services.showUnavailable') }}</span>
    </button>
    <div class="space-y-2">
      <CollapsibleRoot v-for="group in groups" :key="group.id"
        :open="!catalog.collapsedGroups.includes(group.id)"
        @update:open="catalog.setGroupOpen(group.id, $event)">
        <CollapsibleTrigger
          class="group flex h-9 w-full items-center gap-3 rounded-md px-3 text-left text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          :title="collapsed ? groupLabel(group.id) : undefined" :aria-label="groupLabel(group.id)">
          <component :is="groupIcons[group.id] ?? Cable" class="size-4 shrink-0" />
          <span v-if="!collapsed" class="truncate">{{ groupLabel(group.id) }}</span>
          <ChevronRight v-if="!collapsed" class="ml-auto size-4 shrink-0 transition-transform group-data-[state=open]:rotate-90" />
        </CollapsibleTrigger>
        <CollapsibleContent class="space-y-0.5 pt-1" :class="!collapsed && 'ml-5 border-l border-border pl-2'">
          <template v-for="service in group.services" :key="service.id">
            <template v-if="service.id === 'server'">
              <button v-for="child in [{path:'server/files',label:t('nav.files')},{path:'server/terminal',label:t('nav.terminal')}]"
                :key="child.path" class="flex h-8 w-full items-center gap-3 rounded-md px-3 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                :class="activePath === child.path ? 'bg-accent font-medium text-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground'"
                :title="collapsed ? child.label : undefined" @click="navigate(child.path)">
                <Server v-if="collapsed" class="size-4 shrink-0" /><span v-else>{{ child.label }}</span>
              </button>
            </template>
            <button v-else class="flex h-8 w-full items-center gap-3 rounded-md px-3 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              :class="currentService === service.id ? 'bg-accent font-medium text-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground'"
              :title="collapsed ? service.name : undefined" @click="navigate(servicePath(service.id))">
              <Cable v-if="collapsed" class="size-4 shrink-0" /><span v-else class="truncate" :class="!service.connected && 'opacity-50'">{{ service.name }}</span>
            </button>
          </template>
        </CollapsibleContent>
      </CollapsibleRoot>
    </div>
  </nav>
</template>
