<script setup lang="ts">
import {computed,ref} from "vue"
import {useElementSize} from "@vueuse/core"
import {PanelLeft} from "lucide-vue-next"
import type {ShellProps} from "../model/shell"
import {Button} from "@/shared/ui/button"

import {SidebarProvider,Sidebar,SidebarHeader,SidebarContent,SidebarInset,useSidebar} from "@/shared/ui/sidebar"
import PlatformNav from "./PlatformNav.vue"
import AccountMenu from "./AccountMenu.vue"
import ScopeSidebarTrigger from "./ScopeSidebarTrigger.vue"
import RealtimeStatus from "@/shared/ui/RealtimeStatus.vue"
defineProps<ShellProps>()
const emit=defineEmits<{logout:[]}>()
// Captured from the outer provider; the right panel gets its own provider below.
const globalSidebar=useSidebar()
const scopeOpen=ref(true)
const frame=ref<HTMLElement|null>(null)
const {width}=useElementSize(frame)
const scopeOverlay=computed(()=>width.value<960)
</script>
<template>
  <div ref="frame" class="flex min-w-0 flex-1">
  <SidebarProvider v-model:open="scopeOpen" cookie-name="briareus_scope_sidebar" :keyboard-shortcut="false" :overlay="scopeOverlay" class="min-w-0 flex-1" :style="{'--sidebar-width':'14rem'}">
    <SidebarInset class="min-w-0"><header class="sticky top-0 z-20 grid h-10 shrink-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-1 border-b bg-background/95 px-2 backdrop-blur sm:gap-2 sm:px-4">
      <Button variant="ghost" size="icon" class="size-7 shrink-0" aria-label="Общая навигация" @click="globalSidebar.toggleSidebar"><PanelLeft class="size-4"/></Button>
      <div class="min-w-0"><slot name="workspace-scope"/><h1 id="briareus-page-title" tabindex="-1" class="sr-only">{{heading}}</h1></div>
      <div class="flex shrink-0 items-center gap-1"><RealtimeStatus/><AccountMenu v-if="authenticated||sessionActive" :name="accountName" :email="accountEmail" :busy="busy" @logout="emit('logout')"/><ScopeSidebarTrigger v-if="authenticated"/></div>
    </header><div class="min-w-0 flex-1 p-3 lg:p-4"><div class="mx-auto w-full max-w-[1560px]"><slot/></div></div></SidebarInset>
    <Sidebar v-if="authenticated" side="right" collapsible="offcanvas"><SidebarHeader class="min-h-10 flex-row items-center justify-between px-3"><p class="truncate text-xs font-medium text-muted-foreground">{{scopeName||'Рабочая область'}}</p><ScopeSidebarTrigger close class="shrink-0"/></SidebarHeader><SidebarContent class="p-2"><PlatformNav lane="scope" :active-page="page" :collapsed="!scopeOpen" :public-catalog="!authenticated" :design-preview="designPreview" :presentation-pages="presentationPages"/></SidebarContent></Sidebar>
  </SidebarProvider>
  </div>
</template>
