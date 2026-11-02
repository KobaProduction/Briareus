<script setup lang="ts">
import {CheckboxRoot,CheckboxIndicator,type CheckboxRootProps,type CheckboxRootEmits,useForwardPropsEmits} from "reka-ui"
import {computed,type HTMLAttributes} from "vue"
import {Check} from "lucide-vue-next"
import {cn} from "@/shared/lib/utils"
const props=defineProps<CheckboxRootProps&{class?:HTMLAttributes["class"]}>()
const emits=defineEmits<CheckboxRootEmits>()
const delegated=computed(()=>{const result={...props};delete result.class;return result;})
const forwarded=useForwardPropsEmits(delegated,emits)
</script>
<template><CheckboxRoot v-bind="forwarded" :class="cn('peer size-4 shrink-0 rounded-sm border border-primary shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground',props.class)"><CheckboxIndicator class="flex items-center justify-center text-current"><Check class="size-3.5"/></CheckboxIndicator></CheckboxRoot></template>
