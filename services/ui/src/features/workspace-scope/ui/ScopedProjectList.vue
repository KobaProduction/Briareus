<script setup lang="ts">
import {computed,ref,watch} from "vue"
import type {VerifiedPlatformContext,PlatformProjectProof} from "@/entities/workspace"
import {projectGroups,type WorkspaceArea} from "../model/scope"
import {Button} from "@/shared/ui/button"

const props=defineProps<{
  context:VerifiedPlatformContext
  area:WorkspaceArea
  projectId:string|null
  accepts?:(project:PlatformProjectProof)=>boolean
}>()
const limit=ref(10)
watch(()=>[props.context.user.id,JSON.stringify(props.area),props.projectId],()=>{limit.value=10})
const groups=computed(()=>projectGroups(props.context,props.area,props.projectId)
  .map(group=>({...group,projects:group.projects.filter(project=>!props.accepts||props.accepts(project))}))
  .filter(group=>group.projects.length))
const projects=computed(()=>groups.value.flatMap(group=>group.projects))
const shown=computed(()=>new Set(projects.value.slice(0,limit.value).map(project=>project.id)))
</script>
<template>
  <div class="space-y-6">
    <section v-for="group in groups" :key="group.id" class="space-y-4">
      <h2 v-if="(area.kind==='all'||area.kind==='admin')&&!projectId" class="border-b pb-2 text-sm font-semibold">{{group.name}}</h2>
      <template v-for="project in group.projects" :key="`${context.user.id}:${project.id}`">
        <section v-if="shown.has(project.id)" class="space-y-3">
          <h3 v-if="!projectId" class="text-sm font-medium">{{project.name||'Проект'}}</h3>
          <slot :project="project" :aggregate="!projectId"/>
        </section>
      </template>
    </section>
    <p v-if="!projects.length" class="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">В этой области нет доступных проектов.</p>
    <Button v-if="projects.length>limit" variant="outline" @click="limit+=10">Показать ещё проекты</Button>
  </div>
</template>
