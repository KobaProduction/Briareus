<script setup lang="ts">
import {useId} from "vue"
import {useInvitations} from "../model/use-invitations"
import {invitationPort} from "../api/invitations"
import {Button} from "@/shared/ui/button"
import {Input} from "@/shared/ui/input"
import {Card,CardHeader,CardTitle,CardContent} from "@/shared/ui/card"
const props=defineProps<{users?:{id:string;name:string|null;email:string|null}[]}>()
const emit=defineEmits<{changed:[]}>()
const emailId=useId()
const {capabilities,email,busy,notice,pending,messages,issue,toggleInviter,retry}=useInvitations(invitationPort,()=>emit("changed"))
</script>
<template>
  <Card v-if="capabilities?.can_invite||notice">
    <CardHeader><CardTitle>Приглашения в систему</CardTitle></CardHeader>
    <CardContent class="space-y-4">
      <p v-if="capabilities?.unavailable_reason" role="status" class="text-sm text-muted-foreground">{{messages[capabilities.unavailable_reason]||'Приглашения пока недоступны.'}}</p>
      <form v-if="capabilities?.can_invite" class="flex flex-wrap gap-3" @submit.prevent="issue">
        <label :for="emailId" class="min-w-56 flex-1 text-sm">Электронная почта<Input :id="emailId" v-model="email" type="email" autocomplete="email" required maxlength="254" :disabled="busy||!!pending"/></label>
        <Button class="self-end" :disabled="busy||!!pending||!email||!!capabilities.unavailable_reason">Пригласить</Button>
      </form>
      <div v-if="capabilities?.can_manage_inviters&&props.users" class="space-y-2">
        <p class="text-sm text-muted-foreground">Кто может приглашать пользователей. Операторы уже имеют это право.</p>
        <div v-for="user in props.users" :key="user.id" class="flex items-center justify-between gap-3 border-b py-2 text-sm">
          <span>{{user.name||user.email||'Пользователь'}}</span>
          <Button variant="outline" size="sm" :disabled="busy||!!pending" @click="toggleInviter(user.id)">{{capabilities.inviter_ids.includes(user.id)?'Отозвать inviter':'Разрешить приглашать'}}</Button>
        </div>
      </div>
      <p v-if="notice" role="status" class="text-sm">{{notice}}</p>
      <Button v-if="pending" variant="outline" :disabled="busy" @click="retry">Проверить исходную операцию</Button>
    </CardContent>
  </Card>
</template>
