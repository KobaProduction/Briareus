<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { useI18n } from "vue-i18n"
import type { AccountRecord } from "@/shared/api/control-panel"
import AccountsPanel from "@/features/accounts/AccountsPanel.vue"
import { VcsPolicyPanel } from "@/features/vcs-policy"
import SectionTabs from "@/shared/ui/SectionTabs.vue"
const props = defineProps<{
  provider: AccountRecord["provider"]
  name: string
}>()
const { t } = useI18n()
const section = ref("accounts")
const vcs = computed(
  () => props.provider === "github" || props.provider === "gitlab",
)
const tabs = computed(() => [
  { id: "accounts", label: t("git.accounts") },
  ...(vcs.value ? [{ id: "parameters", label: t("git.parameters") }] : []),
])
function readHash(): void {
  section.value =
    location.hash.split("/")[2] === "parameters" && vcs.value
      ? "parameters"
      : "accounts"
}
function select(value: string): void {
  section.value = value
  history.replaceState(null, "", `#services/${props.provider}/${value}`)
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
      v-if="vcs"
      :model-value="section"
      :items="tabs"
      @update:model-value="select"
    /><AccountsPanel
      v-if="section === 'accounts'"
      :title="name"
      :description="t('git.accountsHint', { provider: name })"
      :providers="[provider]"
      :default-provider="provider"
    /><VcsPolicyPanel
      v-else-if="provider === 'github' || provider === 'gitlab'"
      :provider="provider"
    />
  </div>
</template>
