<script setup lang="ts">
import type { HTMLAttributes, Ref } from "vue"
import { useEventListener, useMediaQuery, useVModel } from "@vueuse/core"
import { TooltipProvider } from "reka-ui"
import { computed, ref } from "vue"
import { cn } from '@/shared/lib/utils'
import { readSidebarOpen,storeSidebarOpen,provideSidebarContext, SIDEBAR_COOKIE_NAME, SIDEBAR_KEYBOARD_SHORTCUT, SIDEBAR_WIDTH, SIDEBAR_WIDTH_ICON } from "./utils"

const props = withDefaults(defineProps<{
  defaultOpen?: boolean
  open?: boolean
  class?: HTMLAttributes["class"]
  keyboardShortcut?: string | false
  cookieName?: string
  overlay?: boolean
}>(), {
  defaultOpen: props=>readSidebarOpen(props.cookieName??SIDEBAR_COOKIE_NAME),
  open: undefined,
  keyboardShortcut: SIDEBAR_KEYBOARD_SHORTCUT,
  cookieName: SIDEBAR_COOKIE_NAME,
})

const emits = defineEmits<{
  "update:open": [open: boolean]
}>()

const viewportMobile = useMediaQuery("(max-width: 768px)")
// Nested workspace sidebars can run out of room before the viewport reaches
// the mobile breakpoint (e.g. another sidebar is already expanded).
const isMobile = computed(() => props.overlay === true || viewportMobile.value)
const openMobile = ref(false)

const open = useVModel(props, "open", emits, {
  defaultValue: props.defaultOpen ?? false,
  passive: (props.open === undefined) as false,
}) as Ref<boolean>

function setOpen(value: boolean) {
  open.value = value // emits('update:open', value)

  storeSidebarOpen(props.cookieName,open.value)
}

function setOpenMobile(value: boolean) {
  openMobile.value = value
}

// Helper to toggle the sidebar.
function toggleSidebar() {
  return isMobile.value ? setOpenMobile(!openMobile.value) : setOpen(!open.value)
}

useEventListener("keydown", (event: KeyboardEvent) => {
  if (props.keyboardShortcut && event.key === props.keyboardShortcut && (event.metaKey || event.ctrlKey)) {
    event.preventDefault()
    toggleSidebar()
  }
})

// We add a state so that we can do data-state="expanded" or "collapsed".
// This makes it easier to style the sidebar with Tailwind classes.
const state = computed(() => open.value ? "expanded" : "collapsed")

provideSidebarContext({
  state,
  open,
  setOpen,
  isMobile,
  openMobile,
  setOpenMobile,
  toggleSidebar,
})
</script>

<template>
  <TooltipProvider :delay-duration="0">
    <div
      :style="{
        '--sidebar-width': SIDEBAR_WIDTH,
        '--sidebar-width-icon': SIDEBAR_WIDTH_ICON,
      }"
      :class="cn('group/sidebar-wrapper flex min-h-svh w-full has-[[data-variant=inset]]:bg-sidebar', props.class)"
      v-bind="$attrs"
    >
      <slot />
    </div>
  </TooltipProvider>
</template>
