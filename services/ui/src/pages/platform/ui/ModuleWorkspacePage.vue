<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,ref} from 'vue'
import {moduleById,moduleLocationHash,parseModuleLocation} from '@/features/modules'
import {moduleGroups} from '@/features/modules'
import type {ModuleId} from '@/features/modules'
import type {VerifiedPlatformContext} from '@/entities/workspace'
import type {RauthyPanelIdentity} from '@/entities/identity'
import type {ConnectionProvider} from '@/features/catalog'
import {ConnectionsWorkspace} from '@/widgets/catalog'
import {loadFilesWorkspace,loadTerminalWorkspace,loadBrowserWorkspace,loadAnalysisWorkspace} from '@/widgets/platform-context'
import {protectedPage} from '@/shared/lib/protected-page'
import {Button} from '@/shared/ui/button'
import {Tabs,TabsList,TabsTrigger} from '@/shared/ui/tabs'
import {Select,SelectTrigger,SelectValue,SelectContent,SelectItem} from '@/shared/ui/select'
const FilesWorkspace=protectedPage(loadFilesWorkspace)
const TerminalWorkspace=protectedPage(loadTerminalWorkspace)
const BrowserWorkspace=protectedPage(loadBrowserWorkspace)
const AnalysisWorkspace=protectedPage(loadAnalysisWorkspace)
const props=withDefaults(defineProps<{initial?:ModuleId;filesProjectCanRequest?:boolean;filesContext?:VerifiedPlatformContext|null;filesIdentity?:RauthyPanelIdentity|null;filesProjectId?:string|null}>(),{initial:'web'})
const emit=defineEmits<{openSessions:[];selectProject:[id:string]}>()
const selected=ref<ModuleId>(props.initial),view=ref('overview')
const module=computed(()=>moduleById(selected.value))
const provider=computed<ConnectionProvider>(()=>selected.value==='gitlab'?'gitlab':selected.value==='coolify'?'coolify':['signoz','infrastructure'].includes(selected.value)?'signoz':'github')
const connections=computed(()=>['github','gitlab','svc','infrastructure','signoz','coolify'].includes(selected.value))
const planned=computed(()=>selected.value==='grafana')
function selectProject(id:string):void{emit('selectProject',id)}
function setView(value:string|number){if(value==='overview'||value==='settings'){view.value=value;location.hash=moduleLocationHash(selected.value,value)}}
function openNodes(){location.hash='platform/nodes'}
function navigate(id:ModuleId){location.hash=moduleLocationHash(id,'overview')}
function read(){const route=parseModuleLocation(location.hash,props.initial);if(route.module==='oauth'){location.hash='platform/oauth';return}if(route.module==='calls'){location.hash='platform/calls';return}if(route.view==='global'){location.hash='platform/settings';return}selected.value=route.module;view.value=route.view}
onMounted(()=>{read();window.addEventListener('hashchange',read)})
onBeforeUnmount(()=>window.removeEventListener('hashchange',read))
</script>
<template><section v-if="module" class="space-y-4">
  <div class="flex flex-wrap items-start justify-between gap-3"><div><p class="text-xs text-muted-foreground">Модули MCP</p><h2 class="mt-1 text-xl font-semibold">{{module.title.ru}}</h2><p class="mt-1 text-sm text-muted-foreground">{{module.summary.ru}}</p></div><Button variant="ghost" size="sm" @click="openNodes">Ноды</Button></div>
  <div class="flex flex-wrap gap-1"><Button v-for="group in moduleGroups" :key="group.id" variant="ghost" size="sm" :class="group.module===selected?'bg-accent':''" @click="group.module&&navigate(group.module)">{{group.name}}</Button></div>
  <div v-for="group in moduleGroups.filter(group=>group.module===selected||group.children?.some(child=>child.id===selected))" :key="group.id" class="flex flex-wrap gap-1"><Button v-for="child in group.children" :key="child.id" size="sm" :variant="selected===child.id?'secondary':'ghost'" @click="navigate(child.id)">{{child.name}}</Button></div>
  <Tabs :model-value="view" @update:model-value="setView"><TabsList><TabsTrigger value="overview">Операции</TabsTrigger><TabsTrigger value="settings">Настройки модуля</TabsTrigger></TabsList></Tabs>
  <section v-if="selected==='browser-external'" class="space-y-3 rounded-lg border border-dashed p-5"><h3 class="text-sm font-medium">Внешний браузер для агентов</h3><p class="text-sm text-muted-foreground">Этот MCP-модуль предназначен для доступа агентов к отдельно подключённому браузеру. Встроенный браузер панели остаётся отдельным рабочим инструментом.</p><p class="text-xs text-muted-foreground">Адрес MCP внешнего браузера и доступ к инструментам разработчика задаются в настройках размещения Web на ноде. Состояние подключения определяется этим размещением и текущими разрешениями агентского сеанса.</p></section>
  <div v-else-if="planned" class="rounded-lg border border-dashed p-5 text-sm text-muted-foreground">{{module.title.ru}}: подключение и управление в разработке. Операции недоступны.</div>
  <p v-else-if="!filesContext" class="text-sm text-muted-foreground">Ожидаем подтверждённый контекст рабочей области.</p>
  <div v-else-if="!filesProjectId" class="space-y-2"><p class="text-sm text-muted-foreground">Выберите проект для просмотра его ресурсов.</p><Select @update:model-value="value=>emit('selectProject',String(value))"><SelectTrigger class="max-w-sm" aria-label="Проект модуля"><SelectValue placeholder="Выберите проект"/></SelectTrigger><SelectContent><SelectItem v-for="project in filesContext.projects" :key="project.id" :value="project.id">{{project.name||'Проект'}}</SelectItem></SelectContent></Select></div>
  <section v-else-if="view==='settings'" class="space-y-3 rounded-lg border p-4"><p class="text-sm text-muted-foreground">Параметры запуска и лимиты принадлежат конкретному размещению {{module.title.ru}} на ноде. Общие параметры интерфейса находятся в настройках системы.</p><Button variant="outline" @click="openNodes">Настроить размещение</Button></section>
  <ConnectionsWorkspace v-else-if="connections" :key="selected" :context="filesContext" :selected-project-id="filesProjectId" :initial-provider="provider"/>
  <FilesWorkspace v-else-if="selected==='files'" :context="filesContext" :selected-project-id="filesProjectId" @select-project="selectProject" @open-sessions="emit('openSessions')"/>
  <TerminalWorkspace v-else-if="selected==='terminal'" :context="filesContext" :selected-project-id="filesProjectId" @select-project="selectProject" @open-sessions="emit('openSessions')"/>
  <BrowserWorkspace v-else-if="selected==='web'" :context="filesContext" :selected-project-id="filesProjectId" @select-project="selectProject" @open-sessions="emit('openSessions')"/>
  <section v-else-if="selected==='serena'" class="space-y-3 rounded-lg border p-4"><h3 class="text-sm font-medium">Serena · проектный LSP</h3><p class="text-sm text-muted-foreground">Навигация по символам, поиск ссылок и редактирование используют рабочую папку проекта на ноде. Её могут совместно использовать Terminal, Git и Files; установка модуля Files для работы Serena не требуется. Каталог проекта задаётся относительно этой папки при размещении Serena.</p><p class="text-sm text-muted-foreground">Наличие компонента в каталоге не подтверждает его запуск. Сборка, лимиты и фактическое состояние показаны в размещениях ноды; каждый вызов требует разрешения текущего агентского сеанса.</p><Button variant="outline" @click="openNodes">Открыть размещения на нодах</Button></section>
  <AnalysisWorkspace v-else-if="selected==='analysis'" :context="filesContext" :selected-project-id="filesProjectId??null"/>
</section><p v-else role="status" class="text-sm text-muted-foreground">Описание выбранного модуля недоступно.</p></template>
