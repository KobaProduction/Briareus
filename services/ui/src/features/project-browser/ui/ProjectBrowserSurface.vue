<script setup lang="ts">
import { computed, onScopeDispose, ref } from "vue";
import type { BrowserInput } from "@/entities/browser";
import { browserKey, browserPoint, browserTextInputs } from "../model/browser-input";

const props = defineProps<{
  preview: string;
  zoom: number;
  height: number;
  busy: boolean;
  allowed: boolean;
}>();
const emit = defineEmits<{
  inputs: [events: BrowserInput[], immediate: boolean];
  notice: [message: string];
}>();
const image = ref<HTMLImageElement | null>(null);
const keyboard = ref<HTMLTextAreaElement | null>(null);
const natural = ref({ width: 1280, height: 720 });
const imageWidth = computed(
  () =>
    `calc(min(100%, ${(75 * natural.value.width) / natural.value.height}vh) * ${props.zoom / 100})`,
);
let composing = false,
  disposed = false;

function captureSize(event: Event): void {
  const target = event.currentTarget;
  if (target instanceof HTMLImageElement && target.naturalWidth && target.naturalHeight)
    natural.value = { width: target.naturalWidth, height: target.naturalHeight };
}
function point(event: MouseEvent) {
  const target = image.value;
  if (!target) return null;
  const rect = target.getBoundingClientRect();
  return browserPoint(event.clientX, event.clientY, {
    left: rect.left,
    top: rect.top,
    width: rect.width,
    height: rect.height,
    naturalWidth: target.naturalWidth,
    naturalHeight: target.naturalHeight,
  });
}
function pointer(event: MouseEvent): void {
  const position = point(event);
  if (!position || event.button !== 0 || !props.allowed) return;
  keyboard.value?.focus({ preventScroll: true });
  emit(
    "inputs",
    [
      {
        kind: "click",
        ...position,
        button: "left",
        click_count: Math.min(2, Math.max(1, event.detail)),
      },
    ],
    true,
  );
}
function wheel(event: WheelEvent): void {
  const position = point(event);
  if (!position || !props.allowed) return;
  const scale = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? props.height : 1;
  emit(
    "inputs",
    [
      {
        kind: "wheel",
        ...position,
        delta_x: Math.max(-10000, Math.min(10000, event.deltaX * scale)),
        delta_y: Math.max(-10000, Math.min(10000, event.deltaY * scale)),
      },
    ],
    false,
  );
}
function sendText(text: string, immediate = false): void {
  if (!text || !props.allowed || disposed) return;
  const events = browserTextInputs(text);
  if (!events) {
    emit("notice", "За один раз можно вставить до 65536 символов");
    return;
  }
  emit("inputs", events, immediate);
}
function input(event?: Event): void {
  if (composing || (event instanceof InputEvent && event.isComposing)) return;
  const target = keyboard.value;
  if (!target) return;
  const text = target.value;
  target.value = "";
  sendText(text);
}
function compositionStart(): void {
  composing = true;
}
function compositionEnd(): void {
  composing = false;
  queueMicrotask(() => {
    if (!disposed) input();
  });
}
function keydown(event: KeyboardEvent): void {
  if (composing || event.isComposing) return;
  if ((event.ctrlKey || event.metaKey) && ["t", "l"].includes(event.key.toLowerCase())) return;
  const value = browserKey(event);
  if (!value || value.kind === "text") return;
  event.preventDefault();
  event.stopPropagation();
  emit("inputs", [value], true);
}
function paste(event: ClipboardEvent): void {
  event.preventDefault();
  if (keyboard.value) keyboard.value.value = "";
  sendText(event.clipboardData?.getData("text/plain") ?? "", true);
}
onScopeDispose(() => {
  disposed = true;
});
</script>
<template>
  <fieldset
    aria-label="Содержимое браузера: мышь и клавиатура"
    :aria-busy="busy"
    class="relative max-h-[75vh] w-full overflow-auto bg-muted/30 text-left focus-within:outline focus-within:outline-ring"
    @click="pointer"
    @keydown="keydown"
    @wheel.prevent="wheel"
  >
    <img
      ref="image"
      :src="preview"
      draggable="false"
      alt="Содержимое выбранной вкладки"
      class="mx-auto block h-auto max-w-none"
      :style="{ width: imageWidth }"
      @load="captureSize"
    >
    <textarea
      ref="keyboard"
      aria-label="Ввод в браузер проекта"
      :disabled="!allowed"
      autocomplete="off"
      autocapitalize="off"
      :spellcheck="false"
      class="absolute left-0 top-0 h-px w-px resize-none overflow-hidden opacity-0"
      @input="input"
      @paste="paste"
      @compositionstart="compositionStart"
      @compositionend="compositionEnd"
    />
  </fieldset>
</template>
