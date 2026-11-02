<script setup lang="ts">
import {
  ScrollAreaCorner,
  ScrollAreaRoot,
  ScrollAreaScrollbar,
  ScrollAreaThumb,
  ScrollAreaViewport,
} from "reka-ui";
import type { HTMLAttributes } from "vue";
import { cn } from "@/shared/lib/utils";

const props = defineProps<{ class?: HTMLAttributes["class"]; label?: string }>();
</script>
<template>
  <ScrollAreaRoot type="auto" :class="cn('relative overflow-hidden', props.class)">
    <ScrollAreaViewport
      class="max-h-[inherit] w-full rounded-[inherit] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      tabindex="0"
      :role="label ? 'region' : undefined"
      :aria-label="label"
      ><slot /></ScrollAreaViewport
    >
    <ScrollAreaScrollbar orientation="vertical" class="flex w-2.5 touch-none select-none p-px"
      ><ScrollAreaThumb class="relative flex-1 rounded-full bg-border" /></ScrollAreaScrollbar
    >
    <ScrollAreaScrollbar orientation="horizontal" class="flex h-2.5 touch-none select-none p-px"
      ><ScrollAreaThumb class="relative flex-1 rounded-full bg-border" /></ScrollAreaScrollbar
    >
    <ScrollAreaCorner />
  </ScrollAreaRoot>
</template>
