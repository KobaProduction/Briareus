<script setup lang="ts">
import { useId } from "vue";
import type { VerifiedPlatformContext } from "@/entities/workspace";
import {
  forgetTerminalRecovery,
  restoreTerminalRecovery,
  saveTerminalRecovery,
  type TerminalPorts,
  terminalCommand,
  terminalJobHistory,
  terminalResources,
  terminalStateLabel,
  useTerminalWorkspace,
} from "@/features/terminal";
import { Button } from "@/shared/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/card";
import { Input } from "@/shared/ui/input";
import { ScrollArea } from "@/shared/ui/scroll-area";

const props = defineProps<{ context: VerifiedPlatformContext; selectedProjectId: string | null }>();
defineEmits<{ selectProject: [id: string]; openSessions: [] }>();
const commandControlId = useId();
const ports: TerminalPorts = {
  history: terminalJobHistory,
  command: terminalCommand,
  resources: terminalResources,
  restore: restoreTerminalRecovery,
  save: saveTerminalRecovery,
  forget: forgetTerminalRecovery,
};
const {
  jobs,
  jobsLoading,
  jobsNotice,
  historyAvailable,
  historyLoaded,
  refreshJobs,
  resources,
  command,
  output,
  notice,
  busy,
  project,
  allowed,
  pendingCommand,
  activeJob,
  execute,
  cancelJob,
  newCommand,
} = useTerminalWorkspace(props, ports);
</script>

<template>
  <Card class="min-w-0">
    <CardHeader><CardTitle>Терминал проекта</CardTitle></CardHeader>
    <CardContent class="space-y-4">
      <p v-if="!project" role="status">Выберите проект.</p>
      <template v-else>
        <p v-if="resources.length" class="text-sm text-muted-foreground">
          Исполнитель проекта подключён. Доступно инструментов: {{ resources.length }}.
        </p>
        <label :for="commandControlId" class="block text-sm"
          >Команда
          <Input
            :id="commandControlId"
            v-model="command"
            class="mt-1 font-mono"
            placeholder="Например: pwd"
            :disabled="busy || pendingCommand"
            @keydown.enter="execute"
          />
        </label>
        <p class="text-xs text-muted-foreground">
          Фоновое задание. Лимит времени задаётся настройками ноды или сервера.
        </p>
        <Button
          :disabled="busy || !allowed || (!command.trim() && !pendingCommand)"
          @click="execute"
          >{{
            busy
              ? "Выполняется…"
              : pendingCommand
                ? activeJob
                  ? "Продолжить чтение"
                  : "Уточнить запуск"
                : "Выполнить"
          }}</Button
        >
        <Button v-if="activeJob" variant="outline" :disabled="!allowed" @click="cancelJob"
          >Остановить</Button
        >
        <Button v-if="pendingCommand" variant="outline" :disabled="busy" @click="newCommand"
          >Новая команда</Button
        >
        <ScrollArea
          v-if="output"
          label="Вывод команды"
          class="max-h-96 rounded-md border bg-muted/30"
          ><pre class="whitespace-pre-wrap p-3 text-xs">{{output}}</pre></ScrollArea
        >
        <section
          v-if="historyAvailable"
          class="space-y-3 border-t pt-4"
          aria-label="Мои задания в проекте"
        >
          <div class="flex items-center justify-between gap-3">
            <h3 class="text-sm font-medium">Мои задания в проекте</h3>
            <Button variant="outline" size="sm" :disabled="jobsLoading" @click="refreshJobs">{{
              jobsLoading ? "Загрузка…" : "Обновить задания"
            }}</Button>
          </div>
          <p v-if="!historyLoaded && !jobsNotice" class="text-sm text-muted-foreground">
            Обновите список для просмотра запущенных и завершённых заданий.
          </p>
          <p v-else-if="historyLoaded && !jobs.length" class="text-sm text-muted-foreground">
            Заданий пока нет.
          </p>
          <ul v-if="jobs.length" class="divide-y rounded-md border" aria-label="Задания терминала">
            <li v-for="job in jobs" :key="job.job_id" class="space-y-1 p-3">
              <div class="flex flex-wrap justify-between gap-2 text-sm">
                <span>{{ job.label || "Команда" }} · {{ terminalStateLabel(job.state) }}</span>
                <span v-if="job.exit_code !== null" class="text-muted-foreground"
                  >Код завершения: {{ job.exit_code }}</span
                >
              </div>
              <pre class="whitespace-pre-wrap break-all text-xs">{{ job.command }}</pre>
              <p class="text-xs text-muted-foreground">
                {{ job.started_at || job.created_at || "Время запуска не подтверждено" }}
              </p>
            </li>
          </ul>
          <p v-if="jobsNotice" role="status" class="text-sm text-muted-foreground">
            {{ jobsNotice }}
          </p>
        </section>
      </template>
      <p v-if="notice" role="status" class="break-words text-sm">{{ notice }}</p>
    </CardContent>
  </Card>
</template>
