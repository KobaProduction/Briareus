<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { useI18n } from "vue-i18n"
import SectionTabs from "@/shared/ui/SectionTabs.vue"
import GhidraProjects from "./GhidraProjects.vue"
import GhidraWorkers from "./GhidraWorkers.vue"
const { t } = useI18n()
const section = ref("projects")
const sections = computed(() => [
  { id: "projects", label: t("analysis.projects") },
  { id: "workers", label: t("services.ghidraWorkers") },
])
function readHash(): void {
  section.value =
    location.hash.split("/")[2] === "workers" ? "workers" : "projects"
}
function select(value: string): void {
  if (value !== "projects" && value !== "workers") return
  section.value = value
  history.replaceState(null, "", `#services/ghidra/${value}`)
}
onMounted(() => {
  readHash()
  window.addEventListener("hashchange", readHash)
})
onBeforeUnmount(() => window.removeEventListener("hashchange", readHash))
</script>
<template>
  <div class="space-y-5">
    <SectionTabs
      :model-value="section"
      :items="sections"
      @update:model-value="select"
    /><GhidraProjects v-if="section === 'projects'" /><GhidraWorkers v-else />
  </div>
</template>
