<script setup lang="ts">
import {computed} from 'vue'
import {usePresentationClock,relativeTime} from '@/shared/lib/presentation-clock'
import {uiPreferences} from '@/shared/lib/preferences'
import DetailHoverCard from './DetailHoverCard.vue'
import {Button} from './button'
const props=defineProps<{value:string}>()
const now=usePresentationClock()
const exact=computed(()=>{const date=new Date(props.value);return Number.isFinite(date.valueOf())?date.toLocaleString(uiPreferences.locale.value,{dateStyle:'full',timeStyle:'long',timeZone:uiPreferences.displayTimeZone.value==='UTC'?'UTC':undefined}):'Время не указано'})
</script>
<template><DetailHoverCard><template #trigger><Button variant="ghost" size="sm" class="-ml-2 h-7 whitespace-nowrap px-2 text-xs font-normal tabular-nums" :aria-label="exact"><time :datetime="value">{{relativeTime(value,now)}}</time></Button></template><p class="text-sm">{{exact}}</p><p class="break-all font-mono text-xs text-muted-foreground">{{value}}</p></DetailHoverCard></template>
