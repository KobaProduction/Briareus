<script setup lang="ts">
import type {ConnectionDraft} from "../../model/connection-draft"
import { useId } from "vue"
import {Input} from "@/shared/ui/input"
import CredentialField from "./CredentialField.vue"
import {Select,SelectTrigger,SelectValue,SelectContent,SelectItem} from "@/shared/ui/select"
defineProps<{disabled:boolean;editing?:boolean}>()
const draft=defineModel<ConnectionDraft>({required:true})
const fieldId = useId()
</script>
<template>
  <fieldset :disabled="disabled" class="space-y-4">
    <legend class="sr-only">Параметры GitLab</legend>
    <label :for="`${fieldId}-url`" class="block space-y-2 text-sm font-medium">Сервер GitLab<Input :id="`${fieldId}-url`" v-model="draft.base_url" type="url" maxlength="2048" required placeholder="https://gitlab.com"/></label>
    <label :for="`${fieldId}-auth`" class="block space-y-2 text-sm font-medium">Тип токена
      <Select v-model="draft.auth_type" :disabled="disabled"><SelectTrigger :id="`${fieldId}-auth`" aria-label="Тип токена GitLab"><SelectValue/></SelectTrigger>
        <SelectContent><SelectItem value="private_token">Private token</SelectItem><SelectItem value="bearer">Bearer token</SelectItem><SelectItem value="job_token">CI job token</SelectItem></SelectContent>
      </Select>
    </label>
    <CredentialField v-model="draft.credential" :disabled="disabled" :optional="editing" :label="draft.auth_type==='job_token'?'CI_JOB_TOKEN':'Токен GitLab'"/>
    <p class="text-xs leading-5 text-muted-foreground">Поддерживаются GitLab.com и собственный сервер. CI job token проверяется по текущему заданию и ограничен его сроком жизни.</p>
  </fieldset>
</template>
