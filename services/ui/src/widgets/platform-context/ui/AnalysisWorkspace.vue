<script setup lang="ts">
import { useId } from "vue";
import type { VerifiedPlatformContext } from "@/entities/workspace";
import {
  createAnalysisClient,
  forgetAnalysisRecovery,
  restoreAnalysisRecovery,
  saveAnalysisRecovery,
  useAnalysisWorkspace,
} from "@/features/analysis";
import { readHandResources } from "@/shared/events";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/shared/ui/select";
import { Textarea } from "@/shared/ui/textarea";

const formId = useId();
const props = defineProps<{ context: VerifiedPlatformContext; selectedProjectId: string | null }>();
const {
  engine,
  catalog,
  tool,
  argumentsText,
  output,
  error,
  busy,
  operation,
  filePath,
  analysisProject,
  selectedTool,
  projectArgument,
  allowed,
  tools,
  execute,
  resume,
  cancel,
  useFile,
  stopTracking,
} = useAnalysisWorkspace(props, {
  resources: async (project, signal) => {
    const scopes = await readHandResources(
      "analysis.resources",
      project,
      ["analysis.import"],
      signal,
    );
    if (!scopes) throw new Error("ANALYSIS_RESOURCE_SCOPE_INVALID");
    return scopes;
  },
  client: createAnalysisClient,
  restore: restoreAnalysisRecovery,
  save: saveAnalysisRecovery,
  forget: forgetAnalysisRecovery,
});
</script>
<template>
  <section class="space-y-4">
    <h2 class="text-lg font-semibold">Анализ проекта</h2>
    <p class="text-sm text-muted-foreground">
      Ghidra и radare2 работают в одном модуле. Каталог и параметры инструментов получаются от
      выбранного анализатора.
    </p>
    <p v-if="!selectedProjectId">Выберите проект в шапке.</p>
    <template v-else>
      <label class="block text-sm" :for="`${formId}-engine`"
        >Анализатор<Select v-model="engine" :disabled="busy || !!operation"
          ><SelectTrigger :id="`${formId}-engine`" aria-label="Анализатор"
            ><SelectValue /></SelectTrigger
          ><SelectContent
            ><SelectItem value="radare2">radare2</SelectItem
            ><SelectItem value="ghidra">Ghidra</SelectItem></SelectContent
          ></Select
        ></label
      ><Button :disabled="busy || !!operation || !allowed" @click="tools"
        >Получить инструменты анализатора</Button
      ><label v-if="catalog.length" class="block text-sm" :for="`${formId}-tool`"
        >Инструмент<Select v-model="tool" :disabled="busy || !!operation"
          ><SelectTrigger :id="`${formId}-tool`" aria-label="Инструмент анализа"
            ><SelectValue /></SelectTrigger
          ><SelectContent
            ><SelectItem v-for="item in catalog" :key="item.name" :value="item.name">{{
              item.title || item.name
            }}</SelectItem></SelectContent
          ></Select
        ></label
      >
      <p v-if="selectedTool" class="text-sm text-muted-foreground">
        {{ selectedTool.description }}
      </p>
      <div v-if="selectedTool" class="space-y-3">
        <details>
          <summary>Параметры инструмента</summary>
          <pre class="max-h-64 overflow-auto text-xs">{{selectedTool.inputSchemaText}}</pre>
        </details>
        <label class="block text-sm" :for="`${formId}-filePath`"
          >Файл внутри проекта<Input
            :id="`${formId}-filePath`"
            v-model="filePath"
            :disabled="busy || !!operation"
            placeholder="Путь загруженного файла"
          /></label
        ><Button variant="outline" :disabled="busy || !filePath" @click="useFile"
          >Подставить файл в параметры</Button
        ><label v-if="projectArgument" class="block text-sm" :for="`${formId}-analysisProject`"
          >Проект внутри анализатора<Input
            :id="`${formId}-analysisProject`"
            v-model="analysisProject"
            :disabled="busy || !!operation"
            :placeholder="projectArgument"
          /><span class="text-xs text-muted-foreground"
            >Идентификатор или имя из результата анализатора; это не UUID проекта Briareus. Если
            поле пусто, используется значение из JSON.</span
          ></label
        ><label class="block text-sm" :for="`${formId}-argumentsText`"
          >Параметры JSON<Textarea
            :id="`${formId}-argumentsText`"
            v-model="argumentsText"
            :disabled="busy || !!operation"
            class="min-h-32 font-mono"
          /></label
        ><Button v-if="!operation" :disabled="busy || !allowed" @click="execute">Выполнить</Button>
      </div>
      <div v-if="operation" class="space-y-2">
        <p v-if="busy">Выполняется операция анализа…</p>
        <Button :disabled="busy || !allowed" @click="resume">Продолжить чтение</Button>
        <Button :disabled="!allowed" variant="outline" @click="cancel">Отменить задание</Button>
        <template v-if="!busy">
          <Button variant="outline" @click="stopTracking">Завершить отслеживание</Button>
          <p class="text-sm text-muted-foreground">Прекращение отслеживания не отменяет задание.</p>
        </template>
      </div>
      <p v-if="error" role="alert" class="break-words text-sm text-destructive">{{ error }}</p>
      <pre
        v-if="output"
        class="max-h-96 overflow-auto rounded border p-3 text-xs"
      >{{output}}</pre></template
    >
  </section>
</template>
