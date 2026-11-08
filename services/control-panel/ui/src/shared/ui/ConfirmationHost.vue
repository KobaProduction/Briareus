<script setup lang="ts">
import { watch } from "vue"
import { AlertDialogRoot, AlertDialogPortal, AlertDialogOverlay, AlertDialogContent, AlertDialogTitle, AlertDialogDescription, AlertDialogCancel, AlertDialogAction } from "reka-ui"
import { useI18n } from "vue-i18n"
import { activeConfirmation, settleConfirmation } from "./confirmation"
import Button from "./Button.vue"
const { t } = useI18n()
let previousFocus: HTMLElement | null = null
watch(activeConfirmation, (request, previous) => { if (request && !previous) previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null }, { flush: "sync" })
function restoreFocus(): void { if (previousFocus?.isConnected) previousFocus.focus() }
</script>
<template>
  <AlertDialogRoot :open="Boolean(activeConfirmation)">
    <AlertDialogPortal>
      <AlertDialogOverlay class="fixed inset-0 z-[1000] bg-black/60 backdrop-blur-[1px]" />
      <AlertDialogContent @close-auto-focus.prevent="restoreFocus" @escape-key-down.prevent="settleConfirmation(false)" class="fixed left-1/2 top-1/2 z-[1001] w-[calc(100%_-_2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-card p-6 text-foreground shadow-2xl">
        <AlertDialogTitle class="text-lg font-semibold">{{ t("common.confirm") }}</AlertDialogTitle>
        <AlertDialogDescription class="mt-3 whitespace-pre-wrap break-words text-sm text-muted-foreground">{{ activeConfirmation?.message }}</AlertDialogDescription>
        <div class="mt-6 flex justify-end gap-2">
          <AlertDialogCancel as-child><Button variant="outline" @click="settleConfirmation(false)">{{ t("common.cancel") }}</Button></AlertDialogCancel>
          <AlertDialogAction as-child><Button @click="settleConfirmation(true)">{{ t("common.confirm") }}</Button></AlertDialogAction>
        </div>
      </AlertDialogContent>
    </AlertDialogPortal>
  </AlertDialogRoot>
</template>
