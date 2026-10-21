<script setup lang="ts">
import {computed,ref} from "vue"
import {Check,ChevronDown,ChevronRight,FolderKanban,Layers,UserRound,UsersRound,ShieldCheck} from "lucide-vue-next"
import type {VerifiedPlatformContext} from "@/entities/workspace/model/proof"
import {areaProjects,areaName,type WorkspaceArea} from "../model/scope"
import {Button} from "@/shared/ui/button"
import {Input} from "@/shared/ui/input"
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription} from "@/shared/ui/dialog"
const props=defineProps<{context:VerifiedPlatformContext;area:WorkspaceArea;projectId:string|null}>()
const emit=defineEmits<{'change-area':[area:WorkspaceArea];'change-project':[id:string|null]}>()
const modal=ref<'teams'|'projects'>('teams'),modalOpen=ref(false),search=ref('')
const projects=computed(()=>areaProjects(props.context,props.area))
const currentProject=computed(()=>projects.value.find(project=>project.id===props.projectId))
const teamRows=computed(()=>[
  {key:'all',name:'Все команды',hint:'Все доступные проекты',icon:Layers,area:{kind:'all'} as WorkspaceArea},
  {key:'personal',name:'Личные проекты',hint:'Проекты моей учётной записи',icon:UserRound,area:{kind:'personal'} as WorkspaceArea},
  ...(props.context.user.role==='operator'?[{key:'admin',name:'Администрирование всех команд',hint:'Все команды и проекты платформы',icon:ShieldCheck,area:{kind:'admin'} as WorkspaceArea}]:[]),
  ...props.context.teams.filter(team=>team.member!==false||props.area.kind==='admin'||props.area.kind==='team'&&props.area.id===team.id).map(team=>({key:team.id,name:team.name||'Команда',hint:team.member===false?'Администратор':team.owner?'Владелец':'Участник',icon:UsersRound,area:{kind:'team',id:team.id} as WorkspaceArea})),
].filter(row=>row.name.toLocaleLowerCase().includes(search.value.toLocaleLowerCase())))
const projectRows=computed(()=>projects.value.filter(project=>(project.name||'Проект').toLocaleLowerCase().includes(search.value.toLocaleLowerCase())))
function open(kind:'teams'|'projects'){search.value='';modal.value=kind;modalOpen.value=true}
function selected(area:WorkspaceArea){return props.area.kind===area.kind&&(area.kind!=='team'||props.area.kind==='team'&&props.area.id===area.id)}
function chooseArea(area:WorkspaceArea){emit('change-area',area);modalOpen.value=false}
function chooseProject(id:string|null){emit('change-project',id);modalOpen.value=false}
function chooseAdministration(){emit('change-area',{kind:'admin'});modalOpen.value=false}
</script>
<template>
  <nav aria-label="Рабочая область" class="flex w-full min-w-0 max-w-full items-center gap-0.5">
    <Button variant="ghost" size="sm" class="h-8 min-w-0 max-w-52 flex-1 shrink basis-0 gap-1.5 px-2" aria-label="Выбрать команду" :title="areaName(context,area)" @click="open('teams')"><UsersRound class="size-3.5 shrink-0 text-muted-foreground"/><span class="min-w-0 truncate">{{areaName(context,area)}}</span><ChevronDown class="size-3 shrink-0 text-muted-foreground"/></Button>
    <ChevronRight class="size-3 shrink-0 text-muted-foreground"/>
    <Button variant="ghost" size="sm" class="h-8 min-w-0 max-w-56 flex-1 shrink basis-0 gap-1.5 px-2" aria-label="Выбрать проект" :title="currentProject?.name||'Все проекты'" @click="open('projects')"><FolderKanban class="size-3.5 shrink-0 text-muted-foreground"/><span class="min-w-0 truncate">{{currentProject?.name||'Все проекты'}}</span><ChevronDown class="size-3 shrink-0 text-muted-foreground"/></Button>
  </nav>
  <Dialog v-model:open="modalOpen"><DialogContent class="max-w-md gap-3 p-5"><DialogHeader><DialogTitle>{{modal==='teams'?'Рабочая область':'Проекты'}}</DialogTitle><DialogDescription>{{modal==='teams'?'Выберите команду или личную область':areaName(context,area)}}</DialogDescription></DialogHeader><Input v-model="search" :placeholder="modal==='teams'?'Найти команду…':'Найти проект…'" aria-label="Поиск области"/><div class="max-h-80 space-y-1 overflow-y-auto">
    <template v-if="modal==='teams'"><Button v-for="row in teamRows" :key="row.key" variant="ghost" class="h-auto w-full justify-start gap-3 px-3 py-2.5 text-left" :aria-pressed="selected(row.area)" @click="chooseArea(row.area)"><component :is="row.icon" class="size-4 shrink-0 text-muted-foreground"/><span class="min-w-0 flex-1"><span class="block truncate text-sm">{{row.name}}</span><span class="block text-xs font-normal text-muted-foreground">{{row.hint}}</span></span><Check v-if="selected(row.area)" class="size-4"/></Button><p v-if="!teamRows.length" class="p-4 text-center text-sm text-muted-foreground">Команды не найдены</p></template>
    <template v-else><Button v-if="context.user.role==='operator'&&area.kind!=='admin'&&!search" variant="ghost" class="w-full justify-start gap-3" @click="chooseAdministration"><ShieldCheck class="size-4 text-muted-foreground"/>Все проекты платформы</Button><Button v-if="!search" variant="ghost" class="w-full justify-between" :aria-pressed="projectId===null" @click="chooseProject(null)"><span class="flex items-center gap-3"><Layers class="size-4 text-muted-foreground"/>{{area.kind==='admin'?'Все проекты платформы':'Все проекты'}}</span><Check v-if="projectId===null" class="size-4"/></Button><Button v-for="project in projectRows" :key="project.id" variant="ghost" class="w-full justify-between gap-3" :aria-pressed="projectId===project.id" @click="chooseProject(project.id)"><span class="truncate">{{project.name||'Проект'}}</span><Check v-if="projectId===project.id" class="size-4 shrink-0"/></Button><p v-if="!projectRows.length" class="p-4 text-center text-sm text-muted-foreground">В этой области нет доступных проектов</p></template>
  </div></DialogContent></Dialog>
</template>
