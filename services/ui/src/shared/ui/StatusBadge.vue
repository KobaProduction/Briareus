<script setup lang="ts">
import {LoaderCircle} from 'lucide-vue-next'
import {Badge} from '@/shared/ui/badge'
import {statusToneClasses,type StatusTone} from './status'
withDefaults(defineProps<{label:string;tone?:StatusTone;busy?:boolean;wrap?:boolean}>(),{wrap:false,tone:'neutral',busy:false})
</script>
<template>
 <Badge variant="outline" :class="[statusToneClasses[tone],wrap?'whitespace-normal':'whitespace-nowrap']" class="max-w-full gap-1.5 px-1.5 py-0.5 text-xs font-medium">
  <LoaderCircle v-if="busy" class="size-3 shrink-0 animate-spin" aria-hidden="true"/>
  {{label}}
 </Badge>
</template>
