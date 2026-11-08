<script setup lang="ts">
import { requestConfirmation } from "@/shared/ui/confirmation"
import { onMounted, reactive, ref } from "vue"
import { InputNumber } from "ant-design-vue"
import { useI18n } from "vue-i18n"
import { controlPanelApi } from "@/shared/api/control-panel"
import { notifications } from "@/shared/notifications/bus"
import Button from "@/shared/ui/Button.vue"
const { t } = useI18n()
const ghidraWorkers = ref<Array<Record<string, unknown>>>([])
const ghidraHeaps = reactive<Record<number, number | null>>({})
const ghidraBusy = ref<number | null>(null)
const ghidraError = ref("")
function updateGhidraHeap(index: number, value: unknown): void {
  ghidraHeaps[index] = typeof value === "number" ? value : null
}
async function loadGhidra(): Promise<void> {
  ghidraError.value = ""
  try {
    const result = await controlPanelApi.analysisWorkers()
    ghidraWorkers.value = result.workers
    await Promise.all(
      result.workers.map(async (worker) => {
        const index = Number(worker.worker_index)
        try {
          ghidraHeaps[index] = (
            await controlPanelApi.workerHeap(index)
          ).configured_max_heap_mb
        } catch {
          ghidraHeaps[index] = null
        }
      }),
    )
  } catch (caught) {
    ghidraError.value =
      caught instanceof Error ? caught.message : String(caught)
  }
}
async function runGhidra(
  index: number,
  action: "heap" | "stop" | "start" | "restart",
): Promise<void> {
  if (ghidraBusy.value !== null) return
  const heap = ghidraHeaps[index]
  if (
    action === "heap" &&
    (!Number.isInteger(heap) || heap === null || heap < 128 || heap > 32768)
  ) {
    ghidraError.value = t("services.ghidraHeapRange")
    return
  }
  if (
    action === "stop" &&
    !await requestConfirmation(t("services.ghidraStopConfirm", { index }))
  )
    return
  ghidraBusy.value = index
  ghidraError.value = ""
  try {
    if (action === "heap" && typeof heap === "number") {
      await controlPanelApi.setWorkerHeap(index, heap)
    }
    if (action === "stop") await controlPanelApi.hardStopWorker(index)
    if (action === "start") await controlPanelApi.startWorker(index)
    if (action === "restart") await controlPanelApi.recoverAnalysisWorker(index)
    await loadGhidra()
    notifications.success(String(t("notifications.saved")))
  } catch (caught) {
    ghidraError.value =
      caught instanceof Error ? caught.message : String(caught)
  } finally {
    ghidraBusy.value = null
  }
}
onMounted(() => {
  void loadGhidra()
})
</script>
<template>
  <section class="settings-card max-w-3xl">
    <h2>{{ t("services.ghidraWorkers") }}</h2>
    <p class="text-xs text-muted-foreground">
      {{ t("services.ghidraHeapHint") }}
    </p>
    <p v-if="ghidraError" role="alert" class="text-sm text-destructive">
      {{ ghidraError }}
    </p>
    <div class="py-3">
      <Button variant="outline" size="sm" @click="loadGhidra">{{
        t("common.refresh")
      }}</Button>
    </div>
    <div
      v-for="worker in ghidraWorkers"
      :key="Number(worker.worker_index)"
      class="setting-row flex-wrap gap-3"
    >
      <span
        ><b>Worker {{ worker.worker_index }}</b
        ><small
          >{{
            worker.error ||
            (worker.enabled === false
              ? t("common.disabled")
              : t("services.active"))
          }}
          · {{ worker.project_name || t("services.noProject") }}</small
        ></span
      >
      <div class="flex flex-wrap items-center gap-2">
        <InputNumber
          :value="ghidraHeaps[Number(worker.worker_index)] ?? undefined"
          :min="128"
          :max="32768"
          :step="64"
          placeholder="MiB"
          class="w-32"
          @update:value="
            (value) => updateGhidraHeap(Number(worker.worker_index), value)
          "
        />
        <Button
          size="sm"
          :disabled="ghidraBusy !== null"
          @click="runGhidra(Number(worker.worker_index), 'heap')"
          >{{ t("services.applyHeap") }}</Button
        >
        <Button
          variant="outline"
          size="sm"
          :disabled="ghidraBusy !== null"
          @click="runGhidra(Number(worker.worker_index), 'stop')"
          >Hard Stop</Button
        >
        <Button
          variant="outline"
          size="sm"
          :disabled="ghidraBusy !== null"
          @click="runGhidra(Number(worker.worker_index), 'start')"
          >Start</Button
        >
        <Button
          variant="outline"
          size="sm"
          :disabled="ghidraBusy !== null"
          @click="runGhidra(Number(worker.worker_index), 'restart')"
          >Restart</Button
        >
      </div>
    </div>
  </section>
</template>
