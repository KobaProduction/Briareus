<script setup lang="ts">
import BrandMark from "@/shared/ui/BrandMark.vue"
import {computed} from "vue"
import type {ShellProps} from "../model/shell"
import {useUiPreferences} from "@/shared/lib/preferences"
import {SidebarProvider,Sidebar,SidebarHeader,SidebarContent} from "@/shared/ui/sidebar"
import PlatformNav from "./PlatformNav.vue"
import ScopeSidebarTrigger from "./ScopeSidebarTrigger.vue"
import WorkspaceFrame from "./WorkspaceFrame.vue"
const props=defineProps<ShellProps>()
const emit=defineEmits<{logout:[]}>()
const preferences=useUiPreferences()
const globalOpen=computed({get:()=>!preferences.sidebarCollapsed.value,set:value=>{preferences.sidebarCollapsed.value=!value}})
</script>
<template>
  <SidebarProvider v-model:open="globalOpen" class="bg-background text-foreground" :style="{'--sidebar-width':'13rem'}">
    <Sidebar collapsible="icon"><SidebarHeader class="min-h-10 flex-row items-center justify-between px-3"><a href="#platform/home" class="flex min-w-0 items-center gap-2.5"><BrandMark/><span class="truncate text-sm font-semibold tracking-tight group-data-[collapsible=icon]:hidden">BRIAREUS</span></a><ScopeSidebarTrigger close label="Закрыть общую навигацию" class="md:hidden"/></SidebarHeader><SidebarContent class="p-2"><PlatformNav lane="global" :active-page="page" :collapsed="!globalOpen" :public-catalog="!authenticated" :design-preview="designPreview" :presentation-pages="presentationPages"/></SidebarContent></Sidebar>
    <WorkspaceFrame v-bind="props" @logout="emit('logout')"><template #workspace-scope><slot name="workspace-scope"/></template><slot/></WorkspaceFrame>
  </SidebarProvider>
</template>
