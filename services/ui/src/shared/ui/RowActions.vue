<script setup lang="ts">
import {ref} from 'vue'
import {MoreHorizontal} from 'lucide-vue-next'
import {Popover,PopoverContent,PopoverTrigger} from '@/shared/ui/popover'
import {Button} from '@/shared/ui/button'
defineProps<{label:string;disabled?:boolean}>()
const open=ref(false)
</script>
<template><Popover v-model:open="open"><PopoverTrigger as-child><Button variant="ghost" size="icon" class="size-7" :disabled="disabled" :aria-label="label"><MoreHorizontal class="size-4"/></Button></PopoverTrigger><PopoverContent align="end" class="w-48 p-1" @click="open=false"><slot/></PopoverContent></Popover></template>
