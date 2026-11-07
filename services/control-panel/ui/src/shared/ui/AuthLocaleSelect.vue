<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { setLocale } from "../i18n"

const { locale } = useI18n()
function change(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  if (value === "ru" || value === "en") setLocale(value)
}
</script>

<template>
  <select :value="locale" aria-label="Language / Язык" class="mt-4 rounded border border-border bg-background p-1 text-sm" @change="change">
    <option value="ru">Русский</option>
    <option value="en">English</option>
  </select>
</template>
