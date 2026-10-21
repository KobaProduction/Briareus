<script setup lang="ts">
import type {CurrentAgentSession} from "../api/current-sessions"
import {Select,SelectTrigger,SelectValue,SelectContent,SelectItem} from "@/shared/ui/select"
defineProps<{items:CurrentAgentSession[];modelValue:string;disabled?:boolean}>()
const emit=defineEmits<{'update:modelValue':[value:string]}>()
</script>
<template>
  <Select :model-value="modelValue||undefined" :disabled="disabled" @update:model-value="value=>emit('update:modelValue',String(value))"><SelectTrigger class="mt-1 w-full" aria-label="Сеанс выполнения"><SelectValue placeholder="Выберите сеанс"/></SelectTrigger><SelectContent><SelectItem v-for="(item,index) in items" :key="item.session_uuid" :value="item.session_uuid">{{item.is_elevated?'С разрешением':'Обычный сеанс'}} · {{index+1}} · до {{new Date(item.hard_expires_at).toLocaleTimeString()}}</SelectItem></SelectContent></Select>
</template>
