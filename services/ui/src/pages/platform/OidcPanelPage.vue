<script setup lang="ts">
import { computed, defineAsyncComponent, defineComponent, h, onBeforeUnmount, onMounted, ref, shallowRef, watch, type Component } from "vue"
import { useI18n } from "vue-i18n"
import { AlertTriangle, Loader2 } from "lucide-vue-next"
import {eventBus} from "@/shared/events/bus"
import {verifiedIdentity} from "@/features/platform/api/rauthy-oidc"
import {validate as validatePlatformContext} from "@/features/platform/api/platform-current"
import { ControlPanelShell } from "@/widgets/control-panel"
import { providerStateChanged } from "@/features/platform"
import { createSessionOpenRecovery, sessionOpenOwnerKey } from "@/features/agent-sessions"
import ProjectEntryGrid from "@/features/workspace-scope/ui/ProjectEntryGrid.vue"
import ScopedProjectList from "@/features/workspace-scope/ui/ScopedProjectList.vue"
import WorkspaceScopeSwitcher from "@/features/workspace-scope/ui/WorkspaceScopeSwitcher.vue"
import {areaName,areaProjects,scopedContext,type WorkspaceArea} from "@/features/workspace-scope/model/scope"
import ConnectionsWorkspace from "@/widgets/catalog/ui/ConnectionsWorkspace.vue"
import ControlPanelAccessPage from "@/pages/platform/ControlPanelAccessPage.vue"
import { oidcPagesForRole, resolveOidcView, countPresentableAgentSessionProjects, preferredAgentSessionProjectId } from "@/features/platform/model/oidc-view-routing"
import { readRauthyPanelState, signOutRauthyPanel, type RauthyPanelIdentity, type RauthyPanelState } from "@/features/platform/api/rauthy-oidc"
import { isPlatformProjectId, readPlatformContext, readProjectContext, type VerifiedPlatformContext } from "@/features/platform/api/platform-current"
import type { ModuleId } from "@/features/modules/types"
import type { PlatformPageId } from "@/features/platform/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/card"
import { Button } from "@/shared/ui/button"
import {protectedPage} from "@/shared/lib/protected-page"
import {boundedLifetime,type BoundedLifetime} from "@/shared/lib/bounded-lifetime"

/** Protected screens have NO reason to load during anonymous Rauthy
 * sign-in. Vue mounts them only when activeContext is an unexpired BFF
 * User+Project proof; code-splitting is presentation, NOT authorization.
 *
 * Missing/stale Dev chunks show a read-only retry, never a guessed owner.
 */
const PlatformAdministration=protectedPage(()=>import("@/widgets/platform-context/ui/PlatformAdministration.vue"))
const AgentsWorkspace=protectedPage(()=>import("@/widgets/platform-context/ui/AgentsWorkspace.vue"))
const TerminalWorkspace=protectedPage(()=>import("@/widgets/platform-context/ui/TerminalWorkspace.vue"))
const FilesWorkspace=protectedPage(()=>import("@/widgets/platform-context/ui/FilesWorkspace.vue"))
const BrowserWorkspace=protectedPage(()=>import("@/widgets/platform-context/ui/BrowserWorkspace.vue"))
const CatalogWorkspace=protectedPage(()=>import("@/widgets/catalog/ui/CatalogWorkspace.vue"))
const NodesPage=protectedPage(()=>import("@/pages/platform/NodesPage.vue"))
const AuthorizationOverview=protectedPage(()=>import("@/widgets/platform-context/ui/AuthorizationOverview.vue"))
const AnalysisWorkspace=protectedPage(()=>import("@/widgets/platform-context/ui/AnalysisWorkspace.vue"))
const ModuleWorkspacePage=protectedPage(()=>import("@/pages/modules/ModuleWorkspacePage.vue"))
const ScopedSessionsWorkspace=protectedPage(()=>import("@/widgets/platform-context/ui/ScopedSessionsWorkspace.vue"))
const AccountProfilePage=protectedPage(()=>import("@/pages/platform/AccountProfilePage.vue"))
const SignalsWorkspace=protectedPage(()=>import("@/widgets/platform-context/ui/SignalsWorkspace.vue"))
const DashboardOverview=protectedPage(()=>import("@/widgets/dashboard/ui/DashboardOverview.vue"))
const PlatformSettingsPage=protectedPage(()=>import("@/pages/platform/PlatformSettingsPage.vue"))

/** First-class Rauthy cookie+PKCE application entry. Fresh, server-bound
 * Platform proof opens the panel layout, NOT a privileged PlatformPort.
 * All module descriptions/settings remain presentation-only unless a
 * separately verified per-action BFF endpoint exists.
 */
type AuthPhase="checking"|"signed_out"|"denied"|"unavailable"|"identity_only"|"verified"
const {t,locale}=useI18n()
const state=ref<AuthPhase>("checking")
const identity=ref<RauthyPanelIdentity|null>(null)
const providerSnapshot=ref<RauthyPanelState|null>(null)
const membership=ref<VerifiedPlatformContext|null>(null)
const selectedProjectId=ref<string|null>(null)
const workspaceArea=ref<WorkspaceArea>({kind:"all"})
const focusedProjectId=ref<string|null>(null)
let focusedIdentity:string|null=null
const sessionOpenRecovery=createSessionOpenRecovery()
const revision=ref(0)
const route=ref<PlatformPageId>("home")
const refreshing=ref(false)
const loggingOut=ref(false)
const error=ref("")
const now=ref(Date.now())
// Presentation-only bounded lifetimes from independently verified BFF facts.
// A wall-clock rollback cannot stretch an already acquired owner lease.
const userLease=shallowRef<BoundedLifetime|null>(null)
const projectLease=shallowRef<BoundedLifetime|null>(null)
let controller:AbortController|null=null
let deadline:ReturnType<typeof setTimeout>|null=null
let clock:ReturnType<typeof setInterval>|null=null
let lastSessionCheck=0
const activeContext=computed(()=>{
  const proof=membership.value, user=identity.value
  return state.value==="verified"&&proof&&user&&
    proof.rauthy.subject===user.subject&&proof.rauthy.issuer===user.issuer&&
    Date.parse(proof.expires_at)>now.value&&Date.parse(user.expires_at)>now.value&&
    (projectLease.value?.remainingMilliseconds()??0)>0&&
    (userLease.value?.remainingMilliseconds()??0)>0
    ? proof:null
})
// Keep the mounted read view during transport recovery. Expired authority
// disables interaction; it is never extended or used to authorize a command.
const workspaceContext=computed(()=>membership.value?scopedContext(membership.value,workspaceArea.value,selectedProjectId.value):null)
const activePage=computed<PlatformPageId>(()=>route.value==="users"&&membership.value?.user.role!=="operator"?"profile":resolveOidcView("#platform/"+route.value,!!membership.value))
const labels=computed(()=>locale.value==="ru"?{
  verified:"Пользователь Briareus подтверждён сервером",
  fetching:"Проверяем сеанс и права доступа…",
  blocked:"Текущая учётная запись Rauthy не имеет подтверждённого доступа Briareus",
  unavailable:"Источник Platform-пользователей пока недоступен; серверные действия закрыты",
  unknown:"Проверка прав завершилась без подтверждённого результата",
  noData:"Данные и действия этого раздела требуют отдельного авторизованного Backend API",
  safe:"Это интерфейс раздела. Сама навигация не подтверждает разрешение выполнять операции.",
  retry:"Повторить проверку",logoutError:"Сервер не подтвердил завершение сеанса. Состояние может быть неизвестным.",
  user:"Пользователь",operator:"Оператор",
  next:"Следующий шаг",sessions:"Работа с AgentSession",
  sessionsHint:"Просмотр действующих сеансов, согласований и разрешённых действий выбранного проекта.",
  enterSessions:"Открыть AgentSession",
  noSessions:"Сервер пока не подтвердил ни одного проекта с доступом к AgentSession.",
}:{
  verified:"Briareus user confirmed by server",
  fetching:"Checking session and current permissions…",
  blocked:"This Rauthy account has no verified Briareus access",
  unavailable:"Platform identity service unavailable; server operations stay disabled",
  unknown:"Server did not verify current privileges",
  noData:"Records and actions in this area require a separate authorized Backend API",
  safe:"This is a section layout; navigating here does not authorize any operation.",
  retry:"Check again",logoutError:"Session revocation was not confirmed. Its state may be unknown.",
  user:"User",operator:"Operator",
  next:"Next step",sessions:"AgentSession workspace",
  sessionsHint:"Review current sessions, approvals, and authorized actions for a selected Project.",
  enterSessions:"Open AgentSessions",
  noSessions:"Server has not verified any Project with AgentSession access.",
})
const heading=computed(()=>t(`platform.navigation.${activePage.value==="browser-managed"?"browserManaged":activePage.value==="browser-external"?"browserExternal":activePage.value}`))
const moduleForPage:Partial<Record<PlatformPageId,ModuleId>>={
  files:"files",terminal:"terminal",
  "browser-managed":"web","browser-external":"browser-external",analysis:"analysis",

}
const currentModule=computed(()=>moduleForPage[activePage.value]??null)
const actionableProjectCount=computed(()=>countPresentableAgentSessionProjects(
  workspaceContext.value?.projects??[],
))
const filesProjectReady=computed(()=>activeContext.value?.projects.some(project=>
  project.id===selectedProjectId.value&&project.permissions.includes("use_resources"))??false)
function selectProject(id:string|null):void {
  const context=membership.value
  if(context&&(id===null||areaProjects(context,workspaceArea.value).some(project=>project.id===id)))selectedProjectId.value=id
}
function selectArea(area:WorkspaceArea):void {
  const context=membership.value
  if(!context||area.kind==='admin'&&context.user.role!=='operator'||area.kind==='team'&&!context.teams.some(team=>team.id===area.id))return
  workspaceArea.value=area;selectedProjectId.value=null
}
function openAgentSessions():void{if(actionableProjectCount.value)window.location.hash="platform/sessions"}



function cancelRequests():void{
  controller?.abort()
  controller=null
  if(deadline!==null){clearTimeout(deadline);deadline=null}
}
let directoryLoading=false
async function hydrateDirectory(){
 if(directoryLoading||!membership.value?.directory_paged||!identity.value||eventBus.state.status!=='connected')return
 directoryLoading=true;const actor=membership.value.user.id,proof=membership.value,user=identity.value
 try{
  const collected:{teams:VerifiedPlatformContext['teams'];projects:VerifiedPlatformContext['projects']}={teams:[],projects:[]}
  for(const kind of ['teams','projects'] as const){let cursor:string|undefined;do{
   const page=await eventBus.request<{items:unknown[];has_more:boolean;next_cursor:string|null}>('platform.directory',{kind,...(cursor?{cursor}:{}),limit:100})
   if(membership.value?.user.id!==actor||!Array.isArray(page.items))return
   const validated=validatePlatformContext({...proof,teams:kind==='teams'?page.items:[],projects:kind==='projects'?page.items:[]},user)
   if(!validated)throw Error('Некорректный каталог рабочей области')
   if(kind==='teams')collected.teams.push(...validated.teams);else collected.projects.push(...validated.projects)
   if(!page.has_more)break
   if(!page.next_cursor||page.next_cursor===cursor)throw Error('Некорректная страница каталога')
   cursor=page.next_cursor
  }while(cursor)}
  if(membership.value?.user.id===actor)membership.value={...membership.value,...collected}
 }catch{error.value='Не удалось получить полный каталог проектов и команд.'}finally{directoryLoading=false}
}
function acceptSnapshot(user:RauthyPanelIdentity,context:VerifiedPlatformContext):void{
  const nextProject=boundedLifetime(Date.parse(context.expires_at)),nextUser=boundedLifetime(Date.parse(user.expires_at))
  if(nextProject.remainingMilliseconds()<=0||nextUser.remainingMilliseconds()<=0)return
  const same=identity.value?.issuer===user.issuer&&identity.value?.subject===user.subject&&membership.value?.user.id===context.user.id
  sessionOpenRecovery.retainOwner(sessionOpenOwnerKey(user.issuer,user.subject,user.client_id,context.user.id))
  if(!same){workspaceArea.value={kind:'all'};selectedProjectId.value=null}
  if(same&&context.directory_paged&&membership.value)context={...context,teams:membership.value.teams,projects:membership.value.projects}
  const area=workspaceArea.value
  if(area.kind==='admin'&&context.user.role!=='operator')workspaceArea.value={kind:'all'}
  if(area.kind==='team'&&!context.teams.some(team=>team.id===area.id))workspaceArea.value={kind:'all'}
  if(selectedProjectId.value&&!areaProjects(context,workspaceArea.value).some(project=>project.id===selectedProjectId.value))selectedProjectId.value=null
  userLease.value=nextUser;projectLease.value=nextProject;identity.value=user;membership.value=context
  void hydrateDirectory()
  now.value=Date.now();state.value="verified";syncRoute()
}
function recoverConnection():void{
  if(!activeContext.value)state.value="unavailable"
}
const stopSnapshot=eventBus.subscribe("platform.context",event=>{
  if(loggingOut.value||providerSnapshot.value?.kind!=="signed_in"||!event.data||typeof event.data!=="object")return
  const data=event.data as Record<string,unknown>,trusted=providerSnapshot.value.identity
  const user=verifiedIdentity(data.identity,{issuer:trusted.issuer,client_id:trusted.client_id})
  if(!user||user.subject!==trusted.subject){console.warn("panel.realtime.identity_rejected");return}
  const context=validatePlatformContext(data.context,user)
  if(!context||(focusedProjectId.value!==null&&(context.projects.length!==1||context.projects[0]?.id!==focusedProjectId.value))){console.warn("panel.realtime.context_rejected");return}
  acceptSnapshot(user,context)
})
const stopRenewal=eventBus.subscribe("session.refresh",()=>{void refresh()})
const stopDenied=eventBus.subscribe("session.denied",()=>{membership.value=null;projectLease.value=null;state.value="denied"})
const stopResync=eventBus.subscribe("system.notifications",event=>{if(event.type==="resync.required")void refresh()})
const stopConnection=eventBus.subscribe("connection.state",event=>{
  if(event.type==='connected')void hydrateDirectory()
  if(["reconnecting","error"].includes(event.type)&&!activeContext.value&&providerSnapshot.value?.kind==="signed_in")state.value="unavailable"
})
function hideAccess():void {
  projectLease.value=null;userLease.value=null
  identity.value=null
  membership.value=null
  selectedProjectId.value=null
  route.value="home"
  if(location.hash!=="#platform/home"){
    history.replaceState(null,"",`${location.pathname}${location.search}#platform/home`)
  }
}
function syncRoute():void{
  const next=resolveOidcView(location.hash,!!membership.value)
  route.value=next
  if(location.hash.split("/")[1]!==next||!location.hash.startsWith("#platform/")){
    if(next==="home")history.replaceState(null,"",`${location.pathname}${location.search}#platform/home`)
  }
}

async function selectProjectScope(id:string|null):Promise<void>{
  if(loggingOut.value||providerSnapshot.value?.kind!=="signed_in"||
    (id!==null&&!isPlatformProjectId(id)))return
  focusedProjectId.value=id
  const provider=providerSnapshot.value.identity
  focusedIdentity=id===null?null:JSON.stringify([provider.issuer,provider.subject,provider.client_id])
  // Unmount commands from the old Project before asking the new owner.
  // Never merge a point proof into the separately bounded inventory.
  state.value="checking";membership.value=null;selectedProjectId.value=null
  await refresh()
}
async function refresh():Promise<void>{
  if(loggingOut.value||refreshing.value)return
  lastSessionCheck=Date.now()
  cancelRequests()
  const request=new AbortController(),run=++revision.value
  controller=request;refreshing.value=true;error.value=""
  deadline=setTimeout(()=>request.abort(),8500)
  try{
    const session=await readRauthyPanelState(request.signal)
    if(run!==revision.value||request.signal.aborted)return
    if(session.kind==="signed_out"){
      providerSnapshot.value=session;eventBus.setSessionActive(false)
      sessionOpenRecovery.clear();focusedProjectId.value=null;focusedIdentity=null
      hideAccess();state.value="signed_out";return
    }
    if(session.kind!=="signed_in"){
      if(providerSnapshot.value?.kind!=="signed_in")providerSnapshot.value=session
      recoverConnection();return
    }
    providerSnapshot.value=session
    let target=focusedProjectId.value
    if(target!==null&&focusedIdentity!==JSON.stringify([session.identity.issuer,session.identity.subject,session.identity.client_id])){
      focusedProjectId.value=null;focusedIdentity=null;target=null
    }
    if(identity.value&&(identity.value.subject!==session.identity.subject||identity.value.issuer!==session.identity.issuer)){
      hideAccess();state.value="checking"
    }
    eventBus.setScope(target)
    if(eventBus.state.status!=="connected"){
      // Browsers hide a rejected WebSocket handshake's HTTP403 behind 1006.
      // Ask the existing cookie-bound BFF route for the actual access result
      // instead of misreporting every unlinked User as a network outage.
      const access=await (target===null?readPlatformContext(session.identity,request.signal):readProjectContext(session.identity,target,request.signal))
      if(run!==revision.value||request.signal.aborted)return
      if(access.kind==='denied'||access.kind==='not_current'){
        eventBus.setSessionActive(false);membership.value=null;projectLease.value=null;state.value='denied';return
      }
      if(access.kind==='verified'){
        acceptSnapshot(session.identity,access.context);eventBus.setSessionActive(true)
      }
      else recoverConnection()
      return
    }
    eventBus.setSessionActive(true)
    const current=validatePlatformContext(await eventBus.request("platform.current",{},request.signal),session.identity)
    if(run!==revision.value||request.signal.aborted)return
    if(current)acceptSnapshot(session.identity,current)
    else recoverConnection()
  }catch{if(run===revision.value)recoverConnection()}
  finally{
    if(run===revision.value){
      if(deadline!==null){clearTimeout(deadline);deadline=null}
      refreshing.value=false;controller=null
      if(request.signal.aborted)recoverConnection()
    }
  }
}
async function logout():Promise<void>{
  if(loggingOut.value||(!activeContext.value&&providerSnapshot.value?.kind!=="signed_in"))return
  loggingOut.value=true
  sessionOpenRecovery.clear();focusedProjectId.value=null;focusedIdentity=null
  cancelRequests()
  const run=++revision.value
  refreshing.value=false
  error.value=""
  providerSnapshot.value=null
  eventBus.setSessionActive(false)
  // Close all action widgets before waiting for the logout response.
  // A live cookie during server IO is not permission to issue more commands.
  hideAccess()
  state.value="checking"
  const request=new AbortController()
  controller=request
  deadline=setTimeout(()=>request.abort(),8500)
  try{
    const result=await signOutRauthyPanel(request.signal)
    if(run!==revision.value)return
    if(result.kind==="revoked"&&!request.signal.aborted){
      providerSnapshot.value={kind:"signed_out"}
      hideAccess()
      state.value="signed_out"
    }else{
      // A prior verified User snapshot must never survive uncertain logout.
      providerSnapshot.value={kind:"unavailable",reason:"session_unavailable"}
      hideAccess()
      state.value="unavailable"
      error.value=labels.value.logoutError
    }
  }finally{
    if(run===revision.value){
      if(deadline!==null){clearTimeout(deadline);deadline=null}
      controller=null;loggingOut.value=false
    }
  }
}
function onLoginProviderState(value:RauthyPanelState|{kind:"checking"}):void {
  if(loggingOut.value||value.kind==="checking"||!providerStateChanged(providerSnapshot.value,value))return
  providerSnapshot.value=value
  if(value.kind==="signed_out"||value.kind==="unavailable"){
    // Invalidate an older /me before it can reopen the previous User's UI.
    if(value.kind==="signed_out"){sessionOpenRecovery.clear();focusedProjectId.value=null;focusedIdentity=null}
    ++revision.value
    cancelRequests()
    refreshing.value=false
    hideAccess()
    state.value=value.kind
    return
  }
  // A changed Rauthy identity still needs independent Platform ownership.
  void refresh()
}
function onVisibility():void{
  now.value=Date.now()
  if(document.visibilityState==="visible")eventBus.ping()
}
function onHash():void{syncRoute()}
watch(activeContext,next=>{
  if(!next){
    if(state.value==="checking")return
    if(state.value==="verified"){
      // The short server proof expired even if a refresh did not complete.
      // Do not keep verified presentation controls mounted on stale evidence.
      state.value="unavailable"
        }
    if(providerSnapshot.value?.kind!=="signed_in")syncRoute()
  }
})
onMounted(()=>{
  // Preserve a requested deep link during the *initial* authentication check.
  // No protected component mounts until the BFF accepts current membership.
  route.value=resolveOidcView(location.hash,true)
  clock=setInterval(()=>{
    now.value=Date.now()
    // Recover bootstrap and expired proofs without asking the visitor to
    // restart authentication after a temporary owner/transport outage.
    if(!activeContext.value&&state.value!=="signed_out"&&now.value-lastSessionCheck>=5000)void refresh()
  },1000)
  window.addEventListener("hashchange",onHash)
  window.addEventListener("popstate",onHash)
  document.addEventListener("visibilitychange",onVisibility)
  void refresh()
})
onBeforeUnmount(()=>{
  stopSnapshot();stopRenewal();stopDenied();stopConnection();stopResync();eventBus.setSessionActive(false)
  sessionOpenRecovery.clear()
  ++revision.value
  cancelRequests()
  if(clock!==null)clearInterval(clock)
  window.removeEventListener("hashchange",onHash)
  window.removeEventListener("popstate",onHash)
  document.removeEventListener("visibilitychange",onVisibility)
  identity.value=null;membership.value=null;selectedProjectId.value=null;focusedProjectId.value=null;focusedIdentity=null
})
</script>

<template>
  <main v-if="!activeContext" class="grid min-h-dvh place-items-center bg-background px-4 py-8 text-foreground">
    <div class="w-full max-w-lg">
      <div class="mb-8 text-center text-sm font-semibold tracking-widest">BRIAREUS</div>
      <div v-if="error" role="alert" class="mb-4 text-sm text-destructive">{{error}}</div>
      <div v-if="state==='checking'" role="status" class="flex justify-center gap-2 text-sm text-muted-foreground"><Loader2 class="size-4 animate-spin" aria-hidden="true"/>{{labels.fetching}}</div>
      <section v-else-if="providerSnapshot?.kind==='signed_in'" role="status" class="space-y-3 text-center">
        <h1 class="text-xl font-semibold">{{state==='denied'?labels.blocked:'Восстанавливаем соединение'}}</h1>
        <p class="text-sm text-muted-foreground">{{state==='denied'?'Обратитесь к администратору для получения доступа.':'Проверяем сеанс и актуальные права. Соединение восстановится автоматически.'}}</p>
        <Button variant="ghost" :disabled="loggingOut" @click="logout">Выйти</Button>
      </section>
      <section v-else-if="providerSnapshot?.kind!=='signed_out'" role="status" class="space-y-3 text-center">
        <h1 class="text-xl font-semibold">Не удаётся проверить сеанс</h1>
        <p class="text-sm text-muted-foreground">Ожидаем восстановления сервиса входа. Проверка продолжится автоматически.</p>
      </section>
      <ControlPanelAccessPage v-else :initial-session="providerSnapshot" managed-logout
        @logout-requested="logout" @provider-state="onLoginProviderState"/>
    </div>
  </main>
  <ControlPanelShell v-else :page="activePage" :heading="heading"
    :authenticated="!!membership" :session-active="providerSnapshot?.kind==='signed_in'" :busy="loggingOut"
    :presentation-pages="membership?oidcPagesForRole(membership.user.role):undefined"
    :presentation-only="!!activeContext" :account-name="membership?.user.name" :account-email="membership?.user.email" :scope-name="membership?(membership.projects.find(project=>project.id===selectedProjectId)?.name||'Ресурсы проектов'):undefined" @logout="logout">
    <template #workspace-scope><WorkspaceScopeSwitcher v-if="membership" :context="membership" :area="workspaceArea" :project-id="selectedProjectId" @change-area="selectArea" @change-project="selectProject"/></template>
    <div v-if="error" role="alert" class="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">{{error}}</div>

    <div v-if="membership&&workspaceContext&&identity" class="space-y-4" :inert="!activeContext||eventBus.state.status!=='connected'">
      <template v-if="activePage==='home'">
        <PlatformAdministration v-if="membership.user.role==='operator'" :context="membership" view="overview" @changed="refresh"/>
        <ProjectEntryGrid v-if="!selectedProjectId" :context="workspaceContext" :area="workspaceArea" @select="selectProject"/>

      </template>
      <PlatformAdministration v-else-if="activePage==='teams'||activePage==='projects'||membership.user.role==='operator'&&activePage==='users'" :key="activePage" :context="membership" :view="activePage" @changed="refresh"/>
      <AgentsWorkspace v-else-if="activePage==='agents'" :context="workspaceContext" :project-id="selectedProjectId"/>
      <ScopedSessionsWorkspace v-else-if="activePage==='sessions'" :context="workspaceContext" :identity="identity" :area="workspaceArea" :selected-project-id="selectedProjectId" :recovery="sessionOpenRecovery"/>
      <ScopedProjectList v-else-if="activePage==='integrations'||activePage==='variables'" :context="workspaceContext" :area="workspaceArea" :project-id="selectedProjectId" :accepts="project=>project.permissions.includes('use_resources')">
        <template #default="{project,aggregate}">
          <ConnectionsWorkspace v-if="activePage==='integrations'" :context="workspaceContext" :selected-project-id="project.id" :embedded="aggregate"/>
          <CatalogWorkspace v-else :context="workspaceContext" :selected-project-id="project.id" kind="variable"/>
        </template>
      </ScopedProjectList>
      <NodesPage v-else-if="activePage==='nodes'" :context="workspaceContext" :project-id="selectedProjectId"/>
      <AuthorizationOverview v-else-if="activePage==='oauth'" :context="membership"/>
      <AnalysisWorkspace v-else-if="activePage==='analysis'" :context="workspaceContext" :selected-project-id="selectedProjectId"/>
      <ProjectEntryGrid v-else-if="!selectedProjectId&&['files','terminal','browser-managed','browser-external','analysis'].includes(activePage)" :context="workspaceContext" :area="workspaceArea" @select="selectProject"/>
      <ModuleWorkspacePage v-else-if="activePage==='mcp'" :files-project-can-request="filesProjectReady" :files-identity="identity" :files-context="workspaceContext" :files-project-id="selectedProjectId" @open-sessions="openAgentSessions" @select-project="selectProject"/>
      <TerminalWorkspace v-else-if="activePage==='terminal'" :context="workspaceContext" :selected-project-id="selectedProjectId" @select-project="selectProject" @open-sessions="openAgentSessions"/>
      <FilesWorkspace v-else-if="activePage==='files'" :context="workspaceContext" :selected-project-id="selectedProjectId" @select-project="selectProject" @open-sessions="openAgentSessions"/>
      <BrowserWorkspace v-else-if="activePage==='browser-managed'" :context="workspaceContext" :selected-project-id="selectedProjectId" @select-project="selectProject" @open-sessions="openAgentSessions"/>
      <SignalsWorkspace v-else-if="activePage==='calls'||activePage==='events'" :key="activePage" :mode="activePage==='calls'?'calls':'events'" :area="workspaceArea" :context="workspaceContext" :selected-project-id="selectedProjectId" @select-project="selectProject"/>
      <ModuleWorkspacePage v-else-if="currentModule" :key="activePage" :initial="currentModule"
        :files-project-can-request="filesProjectReady" :files-identity="identity" :files-context="workspaceContext" :files-project-id="selectedProjectId" @open-sessions="openAgentSessions"/>
      <DashboardOverview v-else-if="activePage==='dashboard'" state="unavailable"/>
      <AccountProfilePage v-else-if="activePage==='profile'" :context="membership"/>
      <PlatformSettingsPage v-else-if="activePage==='settings'"/>
      <Card v-else>
        <CardHeader><CardTitle class="text-base">{{heading}}</CardTitle></CardHeader>
        <CardContent class="space-y-3">
          <AlertTriangle class="size-5 text-muted-foreground" aria-hidden="true"/>
          <p class="text-sm text-muted-foreground">{{labels.noData}}</p>
          <p class="text-xs text-muted-foreground">{{labels.safe}}</p>
        </CardContent>
      </Card>
    </div>
  </ControlPanelShell>
</template>
