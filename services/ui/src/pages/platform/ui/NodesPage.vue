<script setup lang="ts">
import {NodeDirectory} from "@/features/nodes"
import type {VerifiedPlatformContext} from '@/entities/workspace'
defineProps<{context:VerifiedPlatformContext;projectId:string|null}>()
</script>
<template><NodeDirectory :context="context" :project-id="projectId"/></template>
