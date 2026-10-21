<script setup lang="ts">
import {PanelRight,X} from "lucide-vue-next"
import {Button} from "@/shared/ui/button"
import {useSidebar} from "@/shared/ui/sidebar"
const {toggleSidebar,open,isMobile,openMobile}=useSidebar()
defineProps<{close?:boolean;label?:string}>()
</script>
<template><Button variant="ghost" size="icon" class="size-7" :aria-label="label||(close?'Закрыть ресурсы рабочей области':'Ресурсы рабочей области')" :aria-expanded="isMobile?openMobile:open" @click="toggleSidebar"><X v-if="close" class="size-4"/><PanelRight v-else class="size-4"/></Button></template>
