<script setup lang="ts">
import {ref} from 'vue'
import {HoverCardRoot,HoverCardTrigger,HoverCardPortal,HoverCardContent} from 'reka-ui'
withDefaults(defineProps<{label?:string}>(),{label:'Подробности'})
const open=ref(false),pinned=ref(false),focused=ref(false)
function update(value:boolean){if(value||(!pinned.value&&!focused.value))open.value=value}
function toggle(){pinned.value=!pinned.value;open.value=pinned.value}
function close(){pinned.value=false;focused.value=false;open.value=false}
function focus(){focused.value=true;open.value=true}
function blur(){focused.value=false;if(!pinned.value)open.value=false}
</script>
<template>
 <HoverCardRoot :open="open" :open-delay="250" :close-delay="150" @update:open="update">
  <HoverCardTrigger as-child :aria-expanded="open" aria-haspopup="dialog" @click="toggle" @focus="focus" @blur="blur" @keydown.esc="close"><slot name="trigger"/></HoverCardTrigger>
  <HoverCardPortal><HoverCardContent :side-offset="8" align="start" role="dialog" :aria-label="label" class="z-50 w-80 max-w-[calc(100vw-2rem)] space-y-3 rounded-lg border border-border bg-popover p-4 text-sm text-popover-foreground shadow-xl" @escape-key-down="close" @pointer-down-outside="close" @focus-outside="close"><slot/></HoverCardContent></HoverCardPortal>
 </HoverCardRoot>
</template>
