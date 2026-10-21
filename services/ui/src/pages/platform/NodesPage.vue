<script setup lang="ts">
import NodeDirectory from '@/features/nodes/ui/NodeDirectory.vue'
import type {VerifiedPlatformContext} from '@/entities/workspace/model/proof'
defineProps<{context:VerifiedPlatformContext;projectId:string|null}>()
</script>
<template><NodeDirectory :context="context" :project-id="projectId"/></template>
