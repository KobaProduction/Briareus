<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, type Component } from "vue"
import { useI18n } from "vue-i18n"
import { ChevronRight, Server, Activity, AppWindow, Bot, Blocks, Database, FileKey, FileText, FolderKanban, GitBranch, Globe, LayoutDashboard, Lock, Settings, ShieldCheck, TerminalSquare, Users, UsersRound, Wrench } from "lucide-vue-next"
import { platformNavigation, visiblePlatformPages } from "@/features/platform"
import type { PlatformPageId } from "@/features/platform"
import { parseModuleLocation, moduleLocationHash } from "@/features/modules"
import {moduleGroups} from "@/features/modules"
import type { ModuleId } from "@/features/modules"
import {Input} from "@/shared/ui/input"
import {
  SidebarGroup, SidebarGroupContent, SidebarGroupLabel,
  SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarMenuSub,
  SidebarMenuSubButton, SidebarMenuSubItem, useSidebar,
} from "@/shared/ui/sidebar"

const props=defineProps<{
  lane?:"global"|"scope"
  collapsed:boolean
  activePage:PlatformPageId
  publicCatalog?:boolean
  designPreview?:boolean
  presentationPages?: readonly PlatformPageId[]
}>()
const {t}=useI18n()
const {isMobile,setOpenMobile}=useSidebar()
function closeMobileDrawer():void {
  if(isMobile.value)setOpenMobile(false)
}
const sections = computed(()=>[
  {key:"work",label:props.lane==='global'?'Система':props.lane==='scope'?'Рабочая область':t("platform.navigation.work")},
  {key:"resources",label:props.lane==='global'?'Инфраструктура':props.lane==='scope'?'Ресурсы':t("platform.navigation.resources")},
  {key:"admin",label:"Администрирование"},
  {key:"console",label:props.lane==='global'?'Аккаунт':props.lane==='scope'?'Диагностика':t("platform.navigation.console")},
] as const)
const globalPages=new Set<PlatformPageId>(["nodes","home","users","teams","projects","dashboard","oauth","events","profile","settings"])
const navigationQuery=ref("")
const previewPage=ref<PlatformPageId|null>(null),previewGroup=ref<string|null>(null)
const expandedPage=computed(()=>previewPage.value??props.activePage)
const expandedGroup=computed(()=>previewGroup.value??moduleGroups.find(group=>group.module===selectedModule.value||group.children?.some(child=>child.id===selectedModule.value))?.id)
function leaveGroup(event:FocusEvent):void{
  const target=event.currentTarget,next=event.relatedTarget
  if(!(target instanceof Element)||!(next instanceof Node)||!target.contains(next))previewGroup.value=null
}

const items=computed(()=>{
  const presentationPages=props.presentationPages
  const available=props.designPreview?platformNavigation:presentationPages
    ?platformNavigation.filter(item=>presentationPages.includes(item.id))
    :props.publicCatalog?platformNavigation:visiblePlatformPages()
  return available.filter(item=>item.id!=='browser-external'&&(!props.lane||(props.lane==='global'?globalPages.has(item.id):!globalPages.has(item.id)))
    &&t(`platform.navigation.${item.title}`).toLocaleLowerCase().includes(navigationQuery.value.trim().toLocaleLowerCase()))
})
function allowed(id:PlatformPageId):boolean {
  if(props.designPreview)return true
  if(props.presentationPages)return props.presentationPages.includes(id)
  return !props.publicCatalog || id==="home"
}
const icons: Record<PlatformPageId, Component> = {
  nodes:Server,profile:Users,home:LayoutDashboard,mcp:AppWindow,users:Users,teams:UsersRound,projects:FolderKanban,
  agents:Bot,sessions:ShieldCheck,integrations:GitBranch,variables:FileKey,
  dashboard:Activity,calls:Blocks,events:Activity,oauth:Wrench,files:FileText,terminal:TerminalSquare,
  "browser-managed":AppWindow,"browser-external":Globe,analysis:Database,settings:Settings,
}
function sectionOf(item:{id:PlatformPageId;section:string}){return item.id==='users'?'admin':item.section}
const directorySelection=ref('available')
function directoryOptions(id:PlatformPageId){return [
  {id:'available',name:'Доступные'},
  {id:id==='teams'?'owned':'personal',name:id==='teams'?'Мои команды':'Личные'},
  ...(props.presentationPages?.includes('users')?[{id:'admin',name:id==='teams'?'Все команды · администратор':'Все проекты · администратор'}]:[]),
]}
function openDirectory(page:PlatformPageId,filter:string){window.location.hash=`platform/${page}/${filter}`;closeMobileDrawer()}
const selectedModule=ref<ModuleId>("web")
function readSelection():void {
  directorySelection.value=window.location.hash.split('/')[2]||'available'
  selectedModule.value=parseModuleLocation(window.location.hash).module
}
function openModule(id:ModuleId):void {
  if(allowed("mcp")){
    window.location.hash=moduleLocationHash(id,"overview")
    closeMobileDrawer()
  }
}
onMounted(()=>{
  readSelection()
  window.addEventListener("hashchange",readSelection)
})
onBeforeUnmount(()=>window.removeEventListener("hashchange",readSelection))
function navigate(id:PlatformPageId){
  if(!allowed(id))return
  window.location.hash=`platform/${id}`
  closeMobileDrawer()
}
</script>
<template>
  <nav :aria-label="t('platform.navigation.title')" class="space-y-2">
    <Input v-if="!collapsed||isMobile" v-model="navigationQuery" class="mb-3 h-8 text-xs" placeholder="Найти раздел…" :aria-label="lane==='global'?'Поиск по системе':'Поиск по ресурсам'"/>
    <SidebarGroup v-for="section in sections.filter(section=>items.some(item=>sectionOf(item)===section.key))" :key="section.key" class="p-0">
      <SidebarGroupLabel>{{section.label}}</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          <SidebarMenuItem v-for="item in items.filter(entry=>sectionOf(entry)===section.key)" :key="item.id" @pointerenter="(event:PointerEvent)=>{if(event.pointerType==='mouse')previewPage=item.id}" @pointerleave="previewPage=null">
            <SidebarMenuButton :is-active="activePage===item.id" :tooltip="t(`platform.navigation.${item.title}`)"
              :disabled="!allowed(item.id)" :aria-disabled="!allowed(item.id)" @click="navigate(item.id)">
              <component :is="icons[item.id]" class="size-4" aria-hidden="true" />
              <span class="min-w-0 flex-1 truncate">{{t(`platform.navigation.${item.title}`)}}</span>
              <Lock v-if="!allowed(item.id)" class="size-3 shrink-0 opacity-70" aria-hidden="true" />
            </SidebarMenuButton>
            <SidebarMenuSub v-if="(item.id==='teams'||item.id==='projects')&&expandedPage===item.id&&(!collapsed||isMobile)">
              <SidebarMenuSubItem v-for="filter in directoryOptions(item.id)" :key="filter.id"><SidebarMenuSubButton as="button" type="button" size="sm" :is-active="directorySelection===filter.id" @click="openDirectory(item.id,filter.id)"><span class="truncate">{{filter.name}}</span></SidebarMenuSubButton></SidebarMenuSubItem>
            </SidebarMenuSub>
            <SidebarMenuSub v-if="item.id==='mcp'&&expandedPage==='mcp'&&allowed('mcp')">
              <SidebarMenuSubItem v-for="group in moduleGroups" :key="group.id" @pointerenter="(event:PointerEvent)=>{if(event.pointerType==='mouse')previewGroup=group.id}" @pointerleave="previewGroup=null" @focusin="previewGroup=group.id" @focusout="leaveGroup">
                <SidebarMenuSubButton as="button" type="button" size="sm" :is-active="activePage==='mcp'&&selectedModule===group.module" :aria-expanded="group.children?expandedGroup===group.id:undefined" @click="group.module&&openModule(group.module)"><span class="min-w-0 flex-1 truncate">{{group.name}}</span><ChevronRight v-if="group.children" class="size-3 shrink-0 transition-transform" :class="expandedGroup===group.id?'rotate-90':''"/></SidebarMenuSubButton>
                <SidebarMenuSub v-if="group.children&&expandedGroup===group.id" class="mx-1 px-2">
                  <SidebarMenuSubItem v-for="child in group.children" :key="child.id"><SidebarMenuSubButton as="button" type="button" size="sm" :is-active="activePage==='mcp'&&selectedModule===child.id" @click="openModule(child.id)"><span>{{child.name}}</span></SidebarMenuSubButton></SidebarMenuSubItem>
                </SidebarMenuSub>
              </SidebarMenuSubItem>
            </SidebarMenuSub>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  </nav>
</template>
