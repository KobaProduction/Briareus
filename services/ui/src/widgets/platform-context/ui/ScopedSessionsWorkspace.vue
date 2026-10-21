<script setup lang="ts">
// Project controllers retain their proof checks and dialogs; one table presents their live snapshots.
import {computed,onMounted,onBeforeUnmount,ref,watch} from "vue"
import {sessionOpenOwnerKey,SessionInspector,isCurrentSessionId,type SessionOpenRecovery} from "@/features/agent-sessions"
import type {RauthyPanelIdentity} from "@/features/platform/api/rauthy-oidc"
import type {VerifiedPlatformContext} from "@/entities/workspace/model/proof"
import type {WorkspaceArea} from "@/features/workspace-scope/model/scope"
import {areaProjects} from "@/features/workspace-scope/model/scope"
import ActivityTable from "@/shared/ui/data-table/ActivityTable.vue"
import type {ActivitySnapshot} from "@/shared/ui/data-table/activity"
import {platformInventory} from "@/features/platform/api/platform-management"
import {projectVerifier} from "@/features/workspace-scope/model/verify-project"
import {Button} from "@/shared/ui/button"
import EditorDialog from "@/shared/ui/EditorDialog.vue"
import {Input} from "@/shared/ui/input"
import {Select,SelectTrigger,SelectValue,SelectContent,SelectItem} from "@/shared/ui/select"
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription} from "@/shared/ui/dialog"
import {Tabs,TabsList,TabsTrigger} from "@/shared/ui/tabs"
import ApprovalQueue from "./ApprovalQueue.vue"
import CurrentAgentSessions from "./CurrentAgentSessions.vue"
import OpenNormalSession from "./OpenNormalSession.vue"
const props=defineProps<{context:VerifiedPlatformContext;identity:RauthyPanelIdentity;area:WorkspaceArea;selectedProjectId:string|null;recovery:SessionOpenRecovery}>()
const tab=ref('sessions')
const lookupMenu=ref(false)
const lookupId=ref(''),lookupProject=ref(props.selectedProjectId||'')
const lookupTarget=ref<{projectId:string;sessionId:string}|null>(null)
function openLookup(){lookupProject.value=props.selectedProjectId||'';lookupId.value='';lookupMenu.value=true}
function inspectLookup(){if(!isCurrentSessionId(lookupId.value.trim())||!projects.value.some(project=>project.id===lookupProject.value))return;lookupTarget.value={projectId:lookupProject.value,sessionId:lookupId.value.trim()};lookupMenu.value=false}
const snapshots=ref<Record<string,ActivitySnapshot>>({})
const projects=computed(()=>areaProjects(props.context,props.area).filter(project=>(!props.selectedProjectId||project.id===props.selectedProjectId)&&project.permissions.some(right=>right==='use_resources'||right==='approve_agent_session')))
const projectNames=computed(()=>Object.fromEntries(projects.value.map(project=>[project.id,project.name||'Проект'])))
const rows=computed(()=>projects.value.flatMap(project=>snapshots.value[project.id]?.rows??[]))
const loading=computed(()=>projects.value.some(project=>!snapshots.value[project.id]||snapshots.value[project.id]?.loading))
const messages=computed(()=>projects.value.flatMap(project=>{const message=snapshots.value[project.id]?.message;return message?[{id:project.id,text:(props.selectedProjectId?'':(project.name||'Проект')+': ')+message}]:[]}))
watch(()=>tab.value+':'+props.context.user.id,()=>{snapshots.value={}},{flush:'sync'})
const actorNames=ref<Record<string,string>>({[props.context.user.id]:props.context.user.name||props.context.user.email||'Вы'})
const directoryRequest=new AbortController()
onMounted(()=>{if(props.context.user.role==='operator')void platformInventory(directoryRequest.signal).then(inventory=>{
  if(!directoryRequest.signal.aborted)actorNames.value=Object.fromEntries(inventory.users.map(user=>[user.id,user.name||user.email||'Пользователь']))
}).catch(()=>{})})
onBeforeUnmount(()=>directoryRequest.abort())
watch(()=>[props.selectedProjectId,JSON.stringify(props.area)],()=>{if(!props.selectedProjectId&&tab.value==='open')tab.value='sessions'})
const ownerKey=computed(()=>sessionOpenOwnerKey(props.identity.issuer,props.identity.subject,props.identity.client_id,props.context.user.id))
const verifiers=computed(()=>Object.fromEntries(projects.value.map(project=>[project.id,projectVerifier(props.context,props.identity,project.id,'approve_agent_session')])))
const userVerifiers=computed(()=>Object.fromEntries(projects.value.map(project=>[project.id,projectVerifier(props.context,props.identity,project.id,'use_resources')])))
</script>
<template>
  <div class="space-y-5">
    <Tabs v-model="tab"><TabsList><TabsTrigger value="sessions">Сеансы</TabsTrigger><TabsTrigger value="approvals">Согласования</TabsTrigger><TabsTrigger value="open" :disabled="!selectedProjectId">Создать сеанс</TabsTrigger></TabsList></Tabs>
    <Button v-if="tab==='sessions'&&projects.length" variant="ghost" size="sm" @click="openLookup">Открыть сеанс по ID</Button>
    <EditorDialog :open="lookupMenu" title="Открыть сеанс по ID" description="Введите полный идентификатор. Проект ограничивает область поиска." submit-label="Открыть" :disabled="!isCurrentSessionId(lookupId.trim())||!projects.some(project=>project.id===lookupProject)" @update:open="value=>lookupMenu=value" @submit="inspectLookup"><label class="block space-y-2 text-sm"><span>ID сеанса</span><Input v-model="lookupId" autocomplete="off" maxlength="36" placeholder="UUID сеанса"/></label><label class="block space-y-2 text-sm"><span>Проект</span><Select v-model="lookupProject"><SelectTrigger aria-label="Проект для поиска сеанса"><SelectValue placeholder="Выберите проект"/></SelectTrigger><SelectContent><SelectItem v-for="project in projects" :key="project.id" :value="project.id">{{project.name||'Проект'}}</SelectItem></SelectContent></Select></label></EditorDialog>
    <Dialog :open="lookupTarget!==null" @update:open="value=>{if(!value)lookupTarget=null}"><DialogContent class="max-h-[85vh] overflow-y-auto"><DialogHeader><DialogTitle>Сеанс</DialogTitle><DialogDescription>Текущее состояние выбранного сеанса</DialogDescription></DialogHeader><SessionInspector v-if="lookupTarget&&projects.some(project=>project.id===lookupTarget!.projectId)" :project-id="lookupTarget.projectId" :session-id="lookupTarget.sessionId" :actor-id="context.user.id" :proof-expires-at="context.expires_at" :can-list="true" :can-approve="projects.find(project=>project.id===lookupTarget!.projectId)?.permissions.includes('approve_agent_session')===true"/></DialogContent></Dialog>

    <p v-if="!selectedProjectId" class="text-xs text-muted-foreground">Все проекты выбранной области. Для создания сеанса выберите проект в шапке.</p>
    <p v-if="!projects.length" class="text-sm text-muted-foreground">Нет доступных проектов в выбранной области.</p>
    <template v-if="tab!=='open'">
      <p v-for="message in messages" :key="message.id" role="status" class="text-sm text-muted-foreground">{{message.text}}</p>
      <ActivityTable :rows="rows" :project-names="projectNames" :show-project="!selectedProjectId" :loading="loading" :label="tab==='sessions'?'Сеансы':'Согласования'"/>
    </template>
    <template v-for="project in projects" :key="project.id">
      <CurrentAgentSessions v-if="tab==='sessions'" renderless :project-id="project.id" :actor-id="context.user.id" :actor-names="actorNames" :proof-expires-at="context.expires_at" :can-list="true" :can-approve="project.permissions.includes('approve_agent_session')" :verify-approver="verifiers[project.id]" @snapshot="value=>snapshots[project.id]=value"/>
      <ApprovalQueue v-else-if="tab==='approvals'" renderless :project-id="project.id" :actor-id="context.user.id" :actor-names="actorNames" :proof-expires-at="context.expires_at" :can-read="true" :can-approve="project.permissions.includes('approve_agent_session')" :verify-approver="verifiers[project.id]" @snapshot="value=>snapshots[project.id]=value"/>
      <OpenNormalSession v-else-if="selectedProjectId===project.id&&project.permissions.includes('use_resources')" :project-id="project.id" :actor-id="context.user.id" :proof-expires-at="context.expires_at" :can-open="true" :can-approve="project.permissions.includes('approve_agent_session')" :verify-user="userVerifiers[project.id]" :owner-key="ownerKey" :recovery="recovery"/>
    </template>
  </div>
</template>
