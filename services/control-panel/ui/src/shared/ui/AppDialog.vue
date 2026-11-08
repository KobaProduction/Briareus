<script setup lang="ts">
import { watch } from "vue"
import { DialogRoot, DialogPortal, DialogOverlay, DialogContent, DialogTitle, DialogClose } from "reka-ui"
import { X } from "lucide-vue-next"
const props = withDefaults(defineProps<{ open: boolean; title: string; width?: string; closeLabel?: string }>(), { width: "760px", closeLabel: "Close" })
let previousFocus: HTMLElement | null = null
watch(() => props.open, (open) => { if (open) previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null }, { flush: "sync" })
function restoreFocus(): void { if (previousFocus?.isConnected) previousFocus.focus() }
const emit = defineEmits<{ close: [] }>()
</script>
<template>
  <DialogRoot :open="open" @update:open="(value) => { if (!value) emit('close') }">
    <DialogPortal>
      <DialogOverlay class="fixed inset-0 z-[900] bg-black/60 backdrop-blur-[1px]" />
      <DialogContent @close-auto-focus.prevent="restoreFocus" :aria-describedby="undefined" class="fixed left-1/2 top-1/2 z-[901] flex max-h-[90dvh] w-[calc(100%_-_2rem)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-xl border border-border bg-card text-foreground shadow-2xl" :style="{ maxWidth: width }">
        <header class="flex shrink-0 items-center justify-between border-b border-border px-5 py-4">
          <DialogTitle class="text-base font-semibold tracking-tight">{{ title }}</DialogTitle>
          <DialogClose :aria-label="closeLabel" class="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"><X class="size-4" /></DialogClose>
        </header>
        <div class="min-h-0 overflow-y-auto overscroll-contain p-5"><slot /></div>
        <footer v-if="$slots.footer" class="flex shrink-0 items-center justify-end gap-2 border-t border-border px-5 py-3"><slot name="footer" /></footer>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
