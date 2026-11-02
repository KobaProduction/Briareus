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
    <legend class="sr-only">Параметры GitHub</legend>
    <label :for="`${fieldId}-auth`" class="block space-y-2 text-sm font-medium">Способ авторизации
      <Select v-model="draft.auth_type" :disabled="disabled"><SelectTrigger :id="`${fieldId}-auth`" aria-label="Способ авторизации GitHub"><SelectValue/></SelectTrigger>
        <SelectContent><SelectItem value="github_token">GitHub token</SelectItem><SelectItem value="github_app">GitHub App</SelectItem></SelectContent>
      </Select>
    </label>
    <label v-if="draft.auth_type==='github_app'" :for="`${fieldId}-app`" class="block space-y-2 text-sm font-medium">App ID
      <Input :id="`${fieldId}-app`" v-model="draft.external_id" required inputmode="numeric" maxlength="32" placeholder="Идентификатор GitHub App"/>
    </label>
    <CredentialField v-model="draft.credential" :pem="draft.auth_type==='github_app'" :disabled="disabled" :optional="editing"
      :label="draft.auth_type==='github_app'?'Приватный ключ приложения · PEM':'Personal access token'"/>
    <p class="text-xs leading-5 text-muted-foreground">{{draft.auth_type==='github_app'?'App ID и PEM-ключ берутся из настроек GitHub App. Проверка подтверждает приложение; доступ к репозиториям определяется его установками.':'Права на репозитории определяются разрешениями вашего токена.'}}</p>
  </fieldset>
</template>
