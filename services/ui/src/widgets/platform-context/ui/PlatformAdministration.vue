<script setup lang="ts">
import {InvitationManagement} from "@/features/platform"
import {computed,ref,watch,onMounted,onBeforeUnmount,useId} from "vue"
import {Plus,Pencil,UsersRound,FolderKanban,UserRound} from "lucide-vue-next"
import type {VerifiedPlatformContext} from "@/entities/workspace"
import {usePlatformAdministration} from "@/features/platform"
import {UsersTable} from "@/entities/user"
import {TeamsTable} from "@/entities/team"
import {ProjectsTable} from "@/entities/project"
import {TeamMembersTable} from "@/features/team-members"
import EditorDialog from "@/shared/ui/EditorDialog.vue"
import {entityNameError} from "@/shared/lib/entity-name"
import {DataTable} from "@/shared/ui/data-table"
import {Button} from "@/shared/ui/button"
import {Select,SelectTrigger,SelectValue,SelectContent,SelectItem} from "@/shared/ui/select"
import {Input} from "@/shared/ui/input"
import {Card,CardHeader,CardTitle,CardContent} from "@/shared/ui/card"
import {Tabs,TabsList,TabsTrigger,TabsContent} from "@/shared/ui/tabs"
const props=defineProps<{context:VerifiedPlatformContext;view:"overview"|"users"|"teams"|"projects"}>()
const emit=defineEmits<{changed:[]}>()
const formId=useId()
const {ru,operator,inventory,loading,busy,blocked,error,notice,teamName,projectName,projectTeam,selectedTeam,selectedUser,editing,pending,team,candidates,ownerNames,createTeam,createProject,addMember,removeMember,retry,edit,saveName}=usePlatformAdministration(()=>props.context,()=>emit('changed'))
const editingDisplay=ref<typeof editing.value>(null)
watch(editing,value=>{if(value)editingDisplay.value=value},{flush:'sync',immediate:true})
const teamTab=ref('members')
const dialog=ref<''|'team'|'project'|'member'>('')
const dialogOpen=ref(false)
const directoryFilter=ref('available')
const visibleTeams=computed(()=>inventory.value?.teams.filter(team=>directoryFilter.value==='admin'?operator.value:directoryFilter.value==='owned'?team.owner_user_id===props.context.user.id:props.context.teams.some(proof=>proof.id===team.id&&proof.member!==false))??[])
const visibleProjects=computed(()=>inventory.value?.projects.filter(project=>directoryFilter.value==='admin'?operator.value:directoryFilter.value==='personal'?project.owner_user_id===props.context.user.id:project.owner_user_id===props.context.user.id||props.context.teams.some(team=>team.id===project.owner_team_id&&team.member!==false))??[])
const personalProjects=computed(()=>props.context.projects.filter(project=>directoryFilter.value==='personal'?project.owner.kind==='user'&&project.owner.id===props.context.user.id:true).map(project=>({id:project.id,name:project.name||'Проект',owner_team_id:project.owner.kind==='team'?project.owner.id:null,owner_user_id:project.owner.kind==='user'?project.owner.id:null})))
const nameError=computed(()=>entityNameError(editing.value?.name??(dialog.value==='team'?teamName.value:projectName.value)))
function openDialog(value:typeof dialog.value){error.value='';notice.value='';teamName.value='';projectName.value='';selectedUser.value='';dialog.value=value;dialogOpen.value=true}
async function create(){
  const kind=dialog.value
  if((kind==='team'||kind==='project')&&nameError.value)return
  if(!kind)return
  const actions={team:createTeam,project:createProject,member:addMember}
  if(await actions[kind]())dialogOpen.value=false
}
watch(()=>props.view,()=>{dialogOpen.value=false;editing.value=null})
watch(selectedTeam,()=>{teamTab.value='members'})
const teamProjects=computed(()=>inventory.value?.projects.filter(project=>project.owner_team_id===selectedTeam.value)??[])
function readTeamRoute(){const segment=window.location.hash.split('/')[2]||'available';directoryFilter.value=['available','owned','personal','admin'].includes(segment)?segment:'available';if(props.view==='teams')selectedTeam.value=/^[0-9a-f-]{36}$/.test(segment)?segment:''}

function openTeam(id:string){if(!id||inventory.value?.teams.some(team=>team.id===id)||props.context.teams.some(team=>team.id===id)){selectedTeam.value=id;window.location.hash='platform/teams'+(id?'/'+id:'')}}
function removeTeamMember(userId:string){
  void removeMember(userId)
}
onMounted(()=>{readTeamRoute();window.addEventListener('hashchange',readTeamRoute)})
onBeforeUnmount(()=>window.removeEventListener('hashchange',readTeamRoute))
</script>

<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <Button v-if="view==='teams'&&team" variant="ghost" size="sm" class="-ml-3 mb-1" @click="openTeam('')">← Все команды</Button>
        <h2 class="text-xl font-semibold">{{view==='users'?(ru?'Пользователи':'Users'):view==='teams'?(team?.name||(ru?'Команды':'Teams')):view==='projects'?(ru?'Проекты':'Projects'):(ru?'Рабочее пространство':'Workspace')}}</h2>
        <p class="mt-1 text-sm text-muted-foreground">{{context.user.name||context.user.email||(ru?'Пользователь':'User')}}</p>
      </div>
      <div v-if="operator&&view!=='overview'" class="flex items-center gap-2">
        <Button v-if="view==='teams'&&team" variant="outline" size="sm" :disabled="blocked" @click="error='';edit('team',team)"><Pencil class="mr-2 size-4"/>Переименовать</Button>
        <Button v-else-if="view==='teams'" size="sm" :disabled="blocked" @click="openDialog('team')"><Plus class="mr-2 size-4"/>Создать команду</Button>
        <Button v-if="view==='projects'||view==='teams'&&team&&teamTab==='projects'" size="sm" :disabled="blocked" @click="projectTeam=team?.id||'';openDialog('project')"><Plus class="mr-2 size-4"/>Создать проект</Button>
      </div>
    </div>
    <DataTable v-if="!operator&&view==='teams'&&!selectedTeam" :rows="context.teams.filter(team=>directoryFilter!=='owned'||team.owner)" :columns="[{key:'name',title:'Команда',dataIndex:'name'}]" label="Мои команды"><template #cell="{row}"><Button variant="ghost" @click="openTeam(row.id)">{{row.name||'Команда'}}</Button></template></DataTable>
    <ProjectsTable v-if="!operator&&view==='projects'" read-only :projects="personalProjects" :owner-names="Object.fromEntries([[context.user.id,context.user.name||context.user.email||'Вы'],...context.teams.map(team=>[team.id,team.name||'Команда'])])" :disabled="true"/>
    <p v-if="error&&!dialogOpen&&!editing" role="alert" class="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{{error}}</p>
    <p v-if="notice" role="status" class="rounded-lg border border-border bg-muted/30 p-3 text-sm">{{notice}}</p>
    <div v-if="pending" class="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm" role="status">
      <p>{{ru?'Ожидаем подтверждения операции. При потере связи повторная отправка проверит исходную операцию и не создаст дубликат.':'Awaiting confirmation. Retrying checks the original operation without creating a duplicate.'}}</p>
      <Button class="mt-3" variant="outline" :disabled="busy" @click="retry">{{busy?(ru?'Сохраняем…':'Saving…'):(ru?'Повторить отправку':'Retry operation')}}</Button>
    </div>
    <p v-if="loading&&!inventory" role="status" class="text-sm text-muted-foreground">{{ru?'Загружаем данные…':'Loading…'}}</p>
    <template v-if="inventory&&(operator||view==='teams'&&team)">
      <p v-if="inventory.truncated" class="text-sm text-muted-foreground">{{ru?'Показаны первые 100 записей.':'Showing the first 100 records.'}}</p>
      <div v-if="view==='overview'" class="grid grid-cols-[repeat(auto-fit,minmax(min(100%,12rem),1fr))] gap-4">
        <Card v-for="stat in [{label:ru?'Пользователи':'Users',count:inventory.users.length,icon:UserRound},{label:ru?'Команды':'Teams',count:inventory.teams.length,icon:UsersRound},{label:ru?'Проекты':'Projects',count:inventory.projects.length,icon:FolderKanban}]" :key="stat.label"><CardContent class="flex min-w-0 items-center gap-4 p-5"><component :is="stat.icon" class="size-7 shrink-0 text-muted-foreground"/><div class="min-w-0"><p class="text-2xl font-semibold tabular-nums">{{stat.count}}</p><p class="text-sm leading-snug break-words text-muted-foreground">{{stat.label}}</p></div></CardContent></Card>
      </div>
      <Card v-if="view==='users'">
        <CardHeader><CardTitle>{{ru?'Пользователи платформы':'Platform users'}}</CardTitle></CardHeader>
        <CardContent class="space-y-5">

          <p class="text-xs text-muted-foreground">{{ru?'Пользователи появляются после первого входа. Учётная запись и роль администратора определяются в Rauthy.':'Users appear after their first sign-in. Accounts and administrator roles are managed in Rauthy.'}}</p>
          <UsersTable :users="inventory.users" :loading="loading"/>
        </CardContent>
      </Card>
      <InvitationManagement v-if="view==='users'" :key="JSON.stringify([context.rauthy.issuer,context.rauthy.subject,context.user.id])" :users="inventory.users" @changed="()=>{}"/>
      <Card v-if="view==='teams'" class="border-0 bg-transparent shadow-none">
        <CardContent class="space-y-5 p-0">
          <template v-if="!team">

          <p v-if="!visibleTeams.length" class="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">{{ru?'Команд пока нет. Создайте первую команду.':'No teams yet. Create your first team.'}}</p>
          <TeamsTable v-else :teams="visibleTeams" :owner-names="ownerNames" :selected-id="selectedTeam" :loading="loading" @select="id=>{openTeam(id);selectedUser=''}"/>
          </template>
          <div v-if="team" class="space-y-4">

            <Tabs v-model="teamTab"><TabsList><TabsTrigger value="members">Участники</TabsTrigger><TabsTrigger value="projects">Проекты</TabsTrigger></TabsList><TabsContent value="members" class="space-y-4">
<Button v-if="operator" size="sm" variant="outline" :disabled="blocked" @click="openDialog('member')"><Plus class="mr-2 size-4"/>Добавить участника</Button>
            <p v-if="operator&&!candidates.length" class="text-xs text-muted-foreground">Нет пользователей для добавления. Новый пользователь появится после первого входа.</p>
            <TeamMembersTable :team-id="team.id" :member-ids="team.member_ids" :owner-id="team.owner_user_id" :users="inventory.users" :disabled="blocked||!operator" :read-only="!operator" @remove="removeTeamMember"/>
            </TabsContent><TabsContent value="projects"><ProjectsTable hide-owner :projects="teamProjects" :owner-names="ownerNames" :disabled="blocked||!operator" :read-only="!operator" :loading="loading" @rename="project=>edit('project',project)"/></TabsContent></Tabs>
          </div>
        </CardContent>
      </Card>
      <Card v-if="view==='projects'" class="border-0 bg-transparent shadow-none">

        <CardContent class="space-y-5 p-0">

          <ProjectsTable :projects="visibleProjects" :owner-names="ownerNames" :disabled="blocked" :loading="loading" @rename="project=>edit('project',project)"/>
        </CardContent>
      </Card>

    </template>
    <EditorDialog :open="!!editing" :title="editingDisplay?.kind==='team'?'Переименовать команду':'Переименовать проект'" description="Измените название и сохраните." :busy="busy" :disabled="blocked||!!nameError||editing?.name.trim()===editing?.expected_name" :error="error||((editing?.name||'')?nameError:'')" @update:open="value=>{if(!value)editing=null}" @submit="saveName">
      <div class="space-y-2 text-sm"><label :for="formId+'-rename'">Название</label><Input v-if="editingDisplay" :id="formId+'-rename'" v-model="editingDisplay.name" required maxlength="255" autocomplete="off" :aria-invalid="!!nameError"/></div>
    </EditorDialog>
    <EditorDialog :open="dialogOpen" :title="dialog==='team'?'Создать команду':dialog==='project'?'Создать проект':'Добавить участника'" description="Заполните данные. Изменения применятся после сохранения." :submit-label="dialog==='team'||dialog==='project'?'Создать':'Добавить'" :busy="busy" :disabled="blocked||((dialog==='team'||dialog==='project')?!!nameError:!selectedUser)" :error="error||((dialog==='team'?teamName:dialog==='project'?projectName:'')?nameError:'')" @update:open="value=>dialogOpen=value" @submit="create">
      <div v-if="dialog==='team'||dialog==='project'" class="space-y-2 text-sm"><label :for="formId+'-create-name'">Название</label><Input v-if="dialog==='team'" :id="formId+'-create-name'" v-model="teamName" required maxlength="255" autocomplete="off"/><Input v-else :id="formId+'-create-name'" v-model="projectName" required maxlength="255" autocomplete="off"/></div>
      <div v-if="dialog==='project'" class="space-y-2 text-sm"><label :for="formId+'-owner'">Владелец проекта</label><Select :model-value="projectTeam||'personal'" @update:model-value="value=>projectTeam=value==='personal'?'':String(value)"><SelectTrigger :id="formId+'-owner'"><SelectValue/></SelectTrigger><SelectContent><SelectItem value="personal">Мой личный проект</SelectItem><SelectItem v-for="item in inventory?.teams" :key="item.id" :value="item.id">{{item.name}}</SelectItem></SelectContent></Select></div>
      <template v-if="dialog==='member'"><Select :model-value="selectedUser||undefined" :disabled="!candidates.length" @update:model-value="value=>selectedUser=String(value)"><SelectTrigger aria-label="Пользователь для добавления"><SelectValue :placeholder="candidates.length?'Выберите пользователя':'Нет доступных пользователей'"/></SelectTrigger><SelectContent><SelectItem v-for="user in candidates" :key="user.id" :value="user.id">{{user.name||user.email}}</SelectItem></SelectContent></Select><p v-if="!candidates.length" class="text-sm text-muted-foreground">Новый пользователь станет доступен для добавления после первого входа.</p></template>
    </EditorDialog>
  </div>
</template>
