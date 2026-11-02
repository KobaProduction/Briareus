<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { Boxes, Database, ShieldAlert } from "lucide-vue-next"
import type { VerifiedPlatformContext } from "@/entities/workspace"
import { useCatalogMetadata, CATALOG_PAGE_LIMIT, type CatalogKind, type CatalogSummary, type CatalogReadStatus as Status } from "@/features/catalog"
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/card"
import { Badge } from "@/shared/ui/badge"
import { Button } from "@/shared/ui/button"
import { Input } from "@/shared/ui/input"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/shared/ui/dialog"
import { Skeleton } from "@/shared/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/shared/ui/table"

/** User-visible owner metadata only. This widget must NEVER request
 * credentials, variable values, lease handles or raw Integration secrets.
 * Catalog row IDs are not executable MCP resource grants.
 */
const props=withDefaults(defineProps<{
  kind:CatalogKind
  context?:VerifiedPlatformContext|null
  /** Parent-owned selection for authenticated Control Panel; unset in local design preview. */
  selectedProjectId?:string|null
  designPreview?:boolean
  previewState?:"empty"|"loading"|"denied"|"unavailable"
}>(),{designPreview:false,previewState:"empty"})

const emit=defineEmits<{selectProject:[id:string]}>()
const {locale}=useI18n()
const strings=computed(()=>locale.value==="ru"?{
  integration:"Интеграции каталога",variable:"Переменные каталога",
  intro:"Только разрешённые метаданные Catalog, без значений секретов и учётных данных.",
  project:"Проект",filter:"Поиск по ключу или идентификатору",
  refresh:"Обновить",name:"Ключ",identifier:"Ресурс",
  owner:"Владелец",version:"Ревизия",kind:"Тип",
  projectOwner:"Проект",teamOwner:"Команда",allOwners:"Все владельцы",
  details:"Данные записи",detailNote:"Только метаданные из последнего ответа Catalog. Значения переменных и учётные данные здесь не запрашиваются.",
  noMatch:"В загруженном списке нет записей по выбранным фильтрам",clear:"Сбросить фильтры",
  limited:"Получено 50 записей — список может быть неполным. Фильтры работают только по загруженным данным.",
  selectionMissing:"Выбранной записи нет в последнем ответе. Это не подтверждает её удаление.",
  expired:"Подтверждение доступа к каталогу истекло. Данные скрыты до новой проверки.",
  empty:"Подтверждённых записей нет",
  loading:"Получаем список метаданных Catalog…",
  denied:"Сервер не подтвердил право просмотра ресурсов проекта",
  unauthorized:"Сеанс входа не подтверждён",
  invalid:"Некорректный или чужой ответ Catalog; список не показан",
  unavailable:"Сервис Catalog недоступен. Данные и операции не выполняются.",
  idle:"Выберите проект с подтверждённым разрешением на ресурсы",
  noWrite:"Создание, удаление, изменение и доступ к значениям требуют отдельного авторизованного API.",
  notPermit:"Запись Catalog не является разрешением на выполнение MCP Hand.",
  design:"Локальная проверка интерфейса: ни данные, ни права не подменяются",
}:{
  integration:"Catalog integrations",variable:"Catalog variables",
  intro:"Only authorized Catalog metadata, no secret values or credentials.",
  project:"Project",filter:"Search by key or identifier",
  refresh:"Refresh",name:"Key",identifier:"Resource",
  owner:"Owner",version:"Revision",kind:"Kind",
  projectOwner:"Project",teamOwner:"Team",allOwners:"All owners",
  details:"Record details",detailNote:"Metadata from the latest Catalog response only. Variable values and credentials are never requested here.",
  noMatch:"No loaded records match these filters",clear:"Clear filters",
  limited:"Received 50 records; the list may be incomplete. Filters apply only to loaded data.",
  selectionMissing:"The selected record is absent from the latest response. This does not confirm deletion.",
  expired:"Catalog access proof expired. Data is hidden pending a new check.",
  empty:"No verified records",
  loading:"Loading Catalog metadata…",
  denied:"Server denied access to Project resources",
  unauthorized:"Login session is not verified",
  invalid:"Invalid or foreign Catalog data; nothing displayed",
  unavailable:"Catalog source unavailable. No data or operations performed.",
  idle:"Select a Project with verified resource access",
  noWrite:"Creation, deletion, updates and secret values require separate authorized APIs.",
  notPermit:"Catalog records are not MCP Hand execution permits.",
  design:"Local UI preview: no substituted records or permissions",
})
const previewProject=ref<string|null>(null)
const project=computed(()=>props.selectedProjectId===undefined?previewProject.value:props.selectedProjectId)
const search=ref("")
const ownerFilter=ref<"all"|"project"|"team">("all")
const { state, records, busy, detailId, selectionNotice, eligible, selectedProof, canFetch } = useCatalogMetadata({
  context: () => props.context, project: () => project.value, kind: () => props.kind,
  designPreview: () => props.designPreview,
})
const detail=computed(()=>state.value==="ready"?records.value.find(row=>row.resource_uuid===detailId.value)??null:null)
const statusForDisplay=computed<Status>(()=>props.designPreview?
  props.previewState==="empty"?"ready":
    props.previewState==="loading"?"loading":
    props.previewState==="denied"?"denied":"unavailable":state.value)
const stateMessage=computed(()=>statusForDisplay.value==="ready"?(records.value.length?strings.value.noMatch:strings.value.empty):strings.value[statusForDisplay.value])
const matched=computed(()=>{
  const token=search.value.trim().toLocaleLowerCase()
  return records.value.filter(item=>(ownerFilter.value==="all"||item.owner.kind===ownerFilter.value)&&(!token||
    item.key.toLocaleLowerCase().includes(token)||
    item.resource_uuid.toLocaleLowerCase().includes(token)))
})
function ownerName(item:CatalogSummary):string {
  return item.owner.kind==='project'
    ?props.context?.projects.find(project=>project.id===item.owner.id)?.name||strings.value.projectOwner
    :props.context?.teams.find(team=>team.id===item.owner.id)?.name||strings.value.teamOwner
}
function selectProject(id:string):void{
  if(!eligible.value.some(row=>row.id===id))return
  if(props.selectedProjectId===undefined)previewProject.value=id
  else emit("selectProject",id)
  search.value=""
}
watch(eligible,rows=>{
  if(props.selectedProjectId!==undefined)return
  if(!rows.some(row=>row.id===previewProject.value)){
    previewProject.value=rows[0]?.id??null
    search.value=""
  }
},{immediate:true})
// Compare identity fields independently: a renewed proof replaces the
// context object but must not reset a still-current dialog or its filters.
watch([()=>project.value,()=>props.kind,()=>props.context?.user.id,
  ()=>props.context?.rauthy.issuer,()=>props.context?.rauthy.subject],()=>{
  search.value="";ownerFilter.value="all"
},{flush:"sync"})
</script>

<template>
  <div class="space-y-4">
    <Card v-if="selectedProjectId===undefined" class="min-w-0">
      <CardHeader>
        <CardTitle class="flex items-center gap-2 text-base">
          <Boxes v-if="kind==='integration'" class="size-5" aria-hidden="true"/>
          <Database v-else class="size-5" aria-hidden="true"/>
          {{kind==='integration'?strings.integration:strings.variable}}
        </CardTitle>
        <p class="text-xs leading-5 text-muted-foreground">{{strings.intro}}</p>
      </CardHeader>
      <CardContent class="space-y-3">
        <p class="text-xs font-semibold text-muted-foreground">{{strings.project}} ({{eligible.length}})</p>
        <fieldset v-if="eligible.length" class="flex flex-wrap gap-2" :aria-label="strings.project">
          <Button v-for="item in eligible" :key="item.id" size="sm"
            :variant="project===item.id?'default':'outline'" :aria-pressed="project===item.id"
            :title="item.id" @click="selectProject(item.id)">
            {{item.name||strings.project}}
          </Button>
        </fieldset>
        <p v-else class="text-xs text-muted-foreground">{{designPreview?strings.design:strings.idle}}</p>
        <p v-if="context&&project&&!selectedProof" role="status" class="text-xs text-muted-foreground">{{strings.denied}}</p>
      </CardContent>
    </Card>
    <Card class="min-w-0">
      <CardHeader class="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle class="text-sm">{{strings.name}} · {{kind==='integration'?strings.integration:strings.variable}}</CardTitle>
        </div>
      </CardHeader>
      <CardContent class="space-y-4">
        <Input v-model="search" :placeholder="strings.filter" :aria-label="strings.filter" maxlength="128"/>
        <fieldset class="flex flex-wrap gap-2" :aria-label="strings.owner">
          <Button v-for="owner in (['all','project','team'] as const)" :key="owner" type="button" size="sm"
            :variant="ownerFilter===owner?'default':'outline'" :aria-pressed="ownerFilter===owner" @click="ownerFilter=owner">
            {{owner==='all'?strings.allOwners:owner==='project'?strings.projectOwner:strings.teamOwner}}
          </Button>
          <Button v-if="search||ownerFilter!=='all'" variant="ghost" size="sm" @click="search='';ownerFilter='all'">{{strings.clear}}</Button>
        </fieldset>
        <p v-if="state==='ready'&&records.length===CATALOG_PAGE_LIMIT" class="text-xs text-muted-foreground" role="status">{{strings.limited}}</p>
        <p v-if="selectionNotice" class="text-xs text-muted-foreground" role="status">{{strings.selectionMissing}}</p>

        <div v-if="statusForDisplay==='loading'" class="space-y-3" role="status">
          <Skeleton v-for="i in 4" :key="i" class="h-10 w-full"/>
        </div>
        <p v-else-if="statusForDisplay!=='ready'||!matched.length" role="status"
          class="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          {{stateMessage}}
        </p>
        <div v-else class="min-w-0 overflow-x-auto rounded-xl border border-border">
          <Table class="min-w-[520px]">
            <TableHeader><TableRow>
              <TableHead>{{strings.name}}</TableHead>
              <TableHead>{{strings.owner}}</TableHead>
              <TableHead>{{strings.details}}</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              <TableRow v-for="item in matched" :key="item.resource_uuid">
                <TableCell class="text-sm font-medium">{{item.key}}</TableCell>
                <TableCell class="text-xs">
                  <Badge variant="outline">{{item.owner.kind==='project'?strings.projectOwner:strings.teamOwner}}</Badge>
                  <p class="mt-1 text-muted-foreground" :title="item.owner.id">{{ownerName(item)}}</p>
                </TableCell>
                <TableCell><Button variant="outline" size="sm" :disabled="!canFetch||busy" @click="detailId=item.resource_uuid;selectionNotice=false">{{strings.details}}</Button></TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
        <p class="flex items-start gap-2 text-xs leading-5 text-muted-foreground">
          <ShieldAlert class="mt-0.5 size-4 shrink-0" aria-hidden="true"/>{{strings.noWrite}}
        </p>
      </CardContent>
    </Card>
    <Dialog :open="detailId!==null" @update:open="open=>{if(!open)detailId=null}">
      <DialogContent class="max-h-[85vh] overflow-y-auto">
        <DialogHeader><DialogTitle>{{strings.details}}</DialogTitle><DialogDescription>{{strings.detailNote}}</DialogDescription></DialogHeader>
        <p v-if="busy" role="status" class="text-sm text-muted-foreground">{{strings.loading}}</p>
        <dl v-else-if="detail" class="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-3 text-sm">
          <dt>{{strings.name}}</dt><dd class="break-all font-mono">{{detail.key}}</dd>
          <dt>{{strings.identifier}}</dt><dd class="break-all font-mono text-xs">{{detail.resource_uuid}}</dd>
          <dt>{{strings.owner}}</dt><dd class="break-all">{{detail.owner.kind==='project'?strings.projectOwner:strings.teamOwner}}<br/><span class="font-mono text-xs">{{detail.owner.id}}</span></dd>
          <dt>{{strings.version}}</dt><dd>{{detail.version}}</dd>
          <dt>{{strings.kind}}</dt><dd>{{detail.kind==='integration'?strings.integration:strings.variable}}</dd>
        </dl>
      </DialogContent>
    </Dialog>
  </div>
</template>
