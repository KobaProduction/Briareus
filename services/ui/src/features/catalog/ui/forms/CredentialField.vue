<script setup lang="ts">
import {Textarea} from "@/shared/ui/textarea"
import {Input} from "@/shared/ui/input"
defineProps<{label:string;pem?:boolean;disabled?:boolean;optional?:boolean}>()
const value=defineModel<string>({required:true})
</script>
<template>
  <label class="block space-y-2 text-sm font-medium">{{label}}
    <Textarea v-if="pem" v-model="value" :required="!optional" autocomplete="off" spellcheck="false" :disabled="disabled" maxlength="32768"
      class="flex min-h-32 w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      placeholder="-----BEGIN PRIVATE KEY-----"/>
    <Input v-else v-model="value" :required="!optional" type="password" autocomplete="new-password" :disabled="disabled" maxlength="32768" :placeholder="optional?'Оставьте пустым, чтобы сохранить ключ':'Введите ключ доступа'"/>
  </label>
</template>
