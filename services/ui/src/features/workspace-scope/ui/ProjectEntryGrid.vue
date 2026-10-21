<script setup lang="ts">
import {computed} from "vue"
import {FolderKanban,ArrowUpRight} from "lucide-vue-next"
import type {VerifiedPlatformContext} from "@/entities/workspace/model/proof"
import {projectGroups,type WorkspaceArea} from "../model/scope"
import {Button} from "@/shared/ui/button"
const props=defineProps<{context:VerifiedPlatformContext;area:WorkspaceArea}>()
const emit=defineEmits<{select:[id:string]}>()
const groups=computed(()=>projectGroups(props.context,props.area,null))
</script>
<template>
  <div class="space-y-5"><p class="text-sm text-muted-foreground">Выберите проект для работы с его ресурсами.</p><section v-for="group in groups" :key="group.id" class="space-y-3"><h2 v-if="(area.kind==='all'||area.kind==='admin')" class="text-sm font-medium text-muted-foreground">{{group.name}}</h2><div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3"><Button v-for="project in group.projects" :key="project.id" variant="outline" class="h-auto min-h-20 justify-start gap-3 p-4 text-left" @click="emit('select',project.id)"><FolderKanban class="size-5 shrink-0 text-muted-foreground"/><span class="min-w-0 flex-1 truncate">{{project.name||'Проект'}}</span><ArrowUpRight class="size-4 shrink-0 text-muted-foreground"/></Button></div></section><p v-if="!groups.length" class="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">В этой области нет доступных проектов.</p></div>
</template>
