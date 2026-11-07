<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { setLocale } from "../i18n"

const { locale } = useI18n()
</script>

<template>
  <div class="mt-5 flex justify-center gap-3 text-xs text-muted-foreground" aria-label="Language / Язык">
    <button type="button" :aria-pressed="locale === 'ru'" class="hover:text-foreground" @click="setLocale('ru')">Русский</button>
    <button type="button" :aria-pressed="locale === 'en'" class="hover:text-foreground" @click="setLocale('en')">English</button>
  </div>
</template>
