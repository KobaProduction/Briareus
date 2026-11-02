<script setup lang="ts">
import {UserRound,Mail,UsersRound} from "lucide-vue-next"
import type {VerifiedPlatformContext} from "@/entities/workspace"
import {Card,CardHeader,CardTitle,CardContent} from "@/shared/ui/card"
import {Badge} from "@/shared/ui/badge"
import {InvitationManagement} from "@/features/platform"
defineProps<{context:VerifiedPlatformContext}>()
</script>
<template>
  <InvitationManagement class="mb-5"/>
  <div class="mx-auto max-w-3xl space-y-5"><div><h2 class="text-xl font-semibold tracking-tight">Мой профиль</h2><p class="mt-1 text-sm text-muted-foreground">Учётная запись и доступные рабочие области</p></div><Card><CardHeader><CardTitle class="flex items-center gap-2 text-base"><UserRound class="size-4"/>{{context.user.name||'Пользователь'}}</CardTitle></CardHeader><CardContent class="space-y-4"><p class="flex items-center gap-2 text-sm"><Mail class="size-4 text-muted-foreground"/>{{context.user.email||'Email не указан'}}</p><Badge variant="secondary">{{context.user.role==='operator'?'Оператор':'Пользователь'}}</Badge></CardContent></Card><Card><CardHeader><CardTitle class="flex items-center gap-2 text-base"><UsersRound class="size-4"/>Команды</CardTitle></CardHeader><CardContent class="space-y-3"><div v-for="team in context.teams" :key="team.id" class="flex items-center justify-between gap-3 border-b pb-3 last:border-0 last:pb-0"><span class="text-sm">{{team.name||'Команда'}}</span><span class="text-xs text-muted-foreground">{{team.owner?'Владелец':'Участник'}}</span></div><p v-if="!context.teams.length" class="text-sm text-muted-foreground">Вы пока не состоите в командах.</p></CardContent></Card></div>
</template>
