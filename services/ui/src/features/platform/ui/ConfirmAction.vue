<script setup lang="ts">
import ConfirmationDialog from '@/shared/ui/ConfirmationDialog.vue'
defineProps<{open:boolean;title:string;detail:string;target:string;busy?:boolean}>()
const emit=defineEmits<{cancel:[];confirm:[]}>()
</script>
<template><ConfirmationDialog :open="open" :title="title" :description="detail" :target="target" :disabled="!target.trim()" :busy="busy" @cancel="emit('cancel')" @confirm="emit('confirm')"/></template>
