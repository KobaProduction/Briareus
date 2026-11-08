<script setup lang="ts">
import { SwitchRoot, SwitchThumb } from "reka-ui"
defineProps<{ modelValue: boolean; disabled?: boolean }>()
const emit = defineEmits<{ "update:modelValue": [value: boolean] }>()
</script>
<template>
  <SwitchRoot
    :model-value="modelValue"
    :disabled="disabled"
    class="peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent bg-input transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-primary"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <SwitchThumb class="pointer-events-none block size-4 rounded-full bg-background shadow-sm transition-transform data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0" />
  </SwitchRoot>
</template>
