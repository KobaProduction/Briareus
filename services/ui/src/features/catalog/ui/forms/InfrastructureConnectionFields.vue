<script setup lang="ts">
import type {ConnectionDraft} from "../../model/connection-draft"
import { useId } from "vue"
import {Input} from "@/shared/ui/input"
import CredentialField from "./CredentialField.vue"
defineProps<{disabled:boolean;editing?:boolean}>()
const draft=defineModel<ConnectionDraft>({required:true})
const fieldId = useId()
</script>
<template>
  <fieldset :disabled="disabled" class="space-y-4">
    <legend class="sr-only">{{draft.provider==='coolify'?'Параметры Coolify':'Параметры SigNoz'}}</legend>
    <label :for="fieldId" class="block space-y-2 text-sm font-medium">{{draft.provider==='coolify'?'Адрес Coolify':'Адрес SigNoz'}}
      <Input :id="fieldId" v-model="draft.base_url" type="url" maxlength="2048" required :placeholder="draft.provider==='coolify'?'https://coolify.example.com':'https://signoz.example.com'"/>
    </label>
    <CredentialField v-model="draft.credential" :disabled="disabled" :optional="editing" :label="draft.provider==='coolify'?'API token Coolify':'API key сервисного аккаунта SigNoz'"/>
    <p class="rounded-md bg-muted/40 p-3 text-xs leading-5 text-muted-foreground">{{draft.provider==='coolify'?'Подключение используется для согласованного проекта Briareus, среды Development. Проверка не запрашивает переменные окружения.':'Ключ сервисного аккаунта используется для метрик, журналов и трассировок. Проверка подтверждает аккаунт SigNoz.'}}</p>
  </fieldset>
</template>
