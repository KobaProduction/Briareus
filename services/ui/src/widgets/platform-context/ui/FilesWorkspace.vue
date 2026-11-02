<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from "vue";
import type { VerifiedPlatformContext } from "@/entities/workspace";
import {
  checkFileTransferSize,
  createFilesClient,
  downloadFileChunks,
  type FileEntry,
  type FileView,
  filesResources,
  readFileView,
  uploadFileChunks,
} from "@/features/files";
import { eventProjectId } from "@/shared/events";
import type { HandEffectScope } from "@/shared/lib/hand-effect-scope";
import { useLiveQuery } from "@/shared/lib/use-live-query";
import { Button } from "@/shared/ui/button";
import ConfirmationDialog from "@/shared/ui/ConfirmationDialog.vue";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/card";
import { Input } from "@/shared/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/shared/ui/table";
import { Textarea } from "@/shared/ui/textarea";

const formId = useId();
const props = defineProps<{ context: VerifiedPlatformContext; selectedProjectId: string | null }>();
defineEmits<{ selectProject: [id: string]; openSessions: [] }>();
const project = computed(() =>
  props.context.projects.find((p) => p.id === props.selectedProjectId),
);
const identityKey = computed(() =>
  JSON.stringify([
    props.context.rauthy.issuer,
    props.context.rauthy.subject,
    props.context.user.id,
    props.selectedProjectId,
  ]),
);
const resources = ref<HandEffectScope[]>([]);
const path = ref(""),
  output = ref(""),
  notice = ref(""),
  busy = ref(false);
const entries = ref<FileEntry[]>([]);
const upload = ref<File | null>(null),
  editing = ref(false),
  previewComplete = ref(false),
  confirmWrite = ref(false),
  writeBusy = ref(false);
const allowed = computed(
  () =>
    !!project.value?.permissions.includes("use_resources") &&
    resources.value.some((scope) => scope.action === "files.read"),
);
const writeAllowed = computed(
  () => allowed.value && resources.value.some((scope) => scope.action === "files.write"),
);
const workspace = createFilesClient(() => {
  if (!project.value || !allowed.value) return null;
  return {
    project_uuid: project.value.id,
    signal: controller?.signal,
  };
});
async function downloadCurrentFile(run: number): Promise<void> {
  const parts = await downloadFileChunks(path.value, workspace, () => run === generation);
  if (!parts) return;
  const object = URL.createObjectURL(new Blob(parts)),
    link = document.createElement("a");
  link.href = object;
  link.download = path.value.split("/").pop() || "file";
  link.click();
  setTimeout(() => URL.revokeObjectURL(object), 1000);
}
function selectUpload(event: Event): void {
  if (event.target instanceof HTMLInputElement) upload.value = event.target.files?.[0] ?? null;
}
async function uploadCurrentFile(run: number): Promise<void> {
  if (upload.value) checkFileTransferSize(upload.value.size);
  const bytes = upload.value
    ? new Uint8Array(await upload.value.arrayBuffer())
    : new TextEncoder().encode(output.value);
  if (!(await uploadFileChunks(path.value, bytes, workspace, () => run === generation))) return;
  upload.value = null;
  editing.value = false;
  notice.value = "Файл сохранён";
}
async function transfer(download = false) {
  if (busy.value || writeBusy.value || !path.value) return;
  writeBusy.value = true;
  notice.value = "";
  const run = generation;
  try {
    if (download) await downloadCurrentFile(run);
    else await uploadCurrentFile(run);
  } catch (error) {
    if (run === generation)
      notice.value =
        error instanceof Error
          ? error.message
          : "Передача не подтверждена. Файл может быть записан частично.";
  } finally {
    if (run === generation) writeBusy.value = false;
    confirmWrite.value = false;
  }
}
let controller: AbortController | null = null,
  generation = 0;
function explain(error: unknown): string {
  const code = error instanceof Error ? error.message : "";
  return code.includes("403") || code.includes("PERMISSION")
    ? "Нет доступа к файлам этого проекта. Обновите страницу или проверьте свои права в проекте."
    : "Файлы или указанный путь недоступны. Обновите подключение; путь должен находиться внутри проекта.";
}
async function load(): Promise<void> {
  if (!project.value || busy.value || writeBusy.value) return;
  controller?.abort();
  const request = new AbortController();
  controller = request;
  const run = ++generation,
    scope = project.value.id;
  notice.value = "";
  try {
    const found = await filesResources(scope, request.signal);
    if (run !== generation) return;
    resources.value = found;
  } catch (error) {
    if (run === generation) {
      resources.value = [];
      notice.value = explain(error);
    }
  }
}
function showFileView(view: FileView, target: string): void {
  if (view.kind === "directory") {
    entries.value = view.entries;
    path.value = target;
  } else if (view.kind === "content") {
    previewComplete.value = view.complete;
    output.value = new TextDecoder().decode(view.bytes);
  } else if (view.kind === "hash") output.value = `SHA-256: ${view.sha256}`;
  else output.value = `${target} · ${view.info.type} · ${view.info.size_bytes} байт`;
}
async function call(
  tool: "file_list" | "file_read" | "file_info" | "file_hash",
  target = path.value,
): Promise<void> {
  if (!project.value || !allowed.value || busy.value || writeBusy.value) return;
  busy.value = true;
  notice.value = "";
  output.value = "";
  const request = new AbortController();
  controller = request;
  const run = generation;
  const _operation = crypto.randomUUID(),
    timer = setTimeout(() => request.abort(), 15000);
  try {
    const view = await readFileView(tool, target, workspace, () => run === generation);
    if (view) showFileView(view, target);
  } catch (error) {
    if (run === generation) {
      notice.value = explain(error);
      entries.value = [];
    }
  } finally {
    clearTimeout(timer);
    if (run === generation) busy.value = false;
  }
}
watch(
  identityKey,
  () => {
    controller?.abort();
    generation++;
    busy.value = false;
    path.value = "";
    entries.value = [];
    output.value = "";
    resources.value = [];
    upload.value = null;
    editing.value = false;
    previewComplete.value = false;
    writeBusy.value = false;
    confirmWrite.value = false;
  },
  { immediate: true },
);
onBeforeUnmount(() => {
  generation++;
  controller?.abort();
});
const liveQuery = useLiveQuery(load, {
  enabled: () => !!project.value,
  paused: () => busy.value || writeBusy.value,
  topics: ["management.events"],
  accept: (event) => eventProjectId(event) === props.selectedProjectId,
});
watch(identityKey, () => liveQuery.invalidate());
</script>

<template>
  <Card
    ><CardHeader><CardTitle>Файлы проекта</CardTitle></CardHeader
    ><CardContent class="space-y-4">
      <p v-if="resources.length" class="text-sm text-muted-foreground">
        Файловое хранилище проекта подключено.
      </p>
      <label class="block" :for="`${formId}-path`"
        >Путь внутри проекта<Input
          :id="`${formId}-path`"
          v-model="path"
          :disabled="busy || writeBusy"
          placeholder="Пустой путь — корневая папка"
        /></label
      >
      <div class="flex flex-wrap gap-2">
        <Button :disabled="busy || writeBusy || !allowed" @click="call('file_list')"
          >Открыть папку</Button
        >
        <Button
          variant="outline"
          :disabled="busy || writeBusy || !allowed || !path"
          @click="call('file_read')"
          >Прочитать файл</Button
        >
        <Button
          variant="outline"
          :disabled="busy || writeBusy || !allowed || !path"
          @click="call('file_info')"
          >Сведения</Button
        >
        <Button
          variant="outline"
          :disabled="busy || writeBusy || !allowed || !path"
          @click="call('file_hash')"
          >Хеш</Button
        >
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          :disabled="busy || writeBusy || !allowed || !path"
          @click="transfer(true)"
          >Скачать файл</Button
        ><Button
          variant="outline"
          :disabled="busy || writeBusy || !writeAllowed || !path || !previewComplete"
          @click="editing = true"
          >Редактировать текст</Button
        ><label class="text-sm" :for="`${formId}-upload`"
          >Загрузить файл<Input
            :id="`${formId}-upload`"
            type="file"
            :disabled="busy || writeBusy || !writeAllowed"
            @change="selectUpload"
          /></label
        ><Button v-if="upload" :disabled="!path || writeBusy" @click="confirmWrite = true"
          >Загрузить по указанному пути</Button
        >
      </div>
      <section v-if="editing" class="space-y-2">
        <Textarea
          v-model="output"
          :disabled="writeBusy"
          aria-label="Текст файла"
          class="min-h-48 font-mono"
        /><Button
          :disabled="writeBusy || !writeAllowed"
          @click="
            upload = null;
            confirmWrite = true;
          "
          >Сохранить текст</Button
        >
      </section>
      <p v-if="notice" role="status">{{ notice }}</p>
      <Table v-if="entries.length"
        ><TableHeader
          ><TableRow
            ><TableHead>Название</TableHead><TableHead>Тип</TableHead><TableHead>Размер</TableHead
            ><TableHead>Действие</TableHead></TableRow
          ></TableHeader
        >
        <TableBody
          ><TableRow v-for="entry in entries" :key="entry.path"
            ><TableCell>{{ entry.name }}</TableCell
            ><TableCell>{{ entry.type === "directory" ? "Папка" : "Файл" }}</TableCell
            ><TableCell>{{ entry.size_bytes }}</TableCell>
            <TableCell
              ><Button
                variant="ghost"
                :disabled="busy || writeBusy || !allowed"
                @click="call(entry.type === 'directory' ? 'file_list' : 'file_read', entry.path)"
                >Открыть</Button
              ></TableCell
            ></TableRow
          ></TableBody
        ></Table
      >
      <section v-if="output" aria-label="Содержимое файла">
        <pre class="overflow-auto whitespace-pre-wrap rounded border p-3 text-sm">{{output}}</pre>
      </section>
      <ConfirmationDialog
        :open="confirmWrite"
        title="Записать файл?"
        :description="`Содержимое ${path} будет заменено. При прерывании передачи файл может быть записан частично.`"
        :busy="writeBusy"
        confirm-label="Записать"
        @update:open="(value) => (confirmWrite = value)"
        @confirm="transfer(false)"
      />
    </CardContent></Card
  >
</template>
