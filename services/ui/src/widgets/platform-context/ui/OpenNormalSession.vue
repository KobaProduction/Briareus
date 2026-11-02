<script setup lang="ts">
import { Clock3, FolderKey, ShieldCheck } from "lucide-vue-next";

import { computed, useId } from "vue";
import { useI18n } from "vue-i18n";
import {
  SessionInspector,
  type SessionOpenViewContext,
  sessionCommands,
  useSessionOpen,
} from "@/features/agent-sessions";
import { Badge } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/card";
import { Input } from "@/shared/ui/input";
import { Skeleton } from "@/shared/ui/skeleton";

const labelId = useId();
const props = withDefaults(defineProps<SessionOpenViewContext>(), { designPreview: false });
const { locale } = useI18n();
const words = computed(() =>
  locale.value === "ru"
    ? {
        title: "Обычная AgentSession",
        description:
          "Создание серверного сеанса в выбранном проекте. Это не выдача расширенных прав.",
        fixed: "Без повышения",
        requestable: "С запросом повышения",
        label: "Описание сеанса (необязательно)",
        placeholder: "Например, агент проверяет исходники проекта",
        create: "Открыть сеанс",
        opening: "Проверяем права и открываем сеанс…",
        inactive: "Вход и доступ к проекту должны быть подтверждены сервером",
        unavailable: "Сервис сеансов недоступен. Новый сеанс не подтверждён.",
        uncertain:
          "Ответ на создание не подтверждён. Сохранён исходный запрос; новый сеанс автоматически не создаётся.",
        retry: "Повторить исходный запрос",
        recoveryExpired:
          "Срок восстановления исходного запроса истёк. Проверьте список сеансов; повторное создание автоматически не выполняется.",
        retained:
          "Незавершённый запрос сохранён. Повтор использует тот же ключ и параметры после новой проверки прав.",
        denied: "Сервер отказал в доступе к выбранному проекту",
        signedOut: "Сеанс входа завершён — авторизуйтесь заново",
        conflict: "Состояние на сервере изменилось — перепроверьте права",
        invalid: "Неверные параметры запроса или неподтверждённый ответ сервера",
        opened: "Новый обычный сеанс подтверждён сервером",
        recovered: "Результат исходного создания восстановлен",
        expires: "Завершится",
        revision: "Ревизия",
        operations: "Разрешённые операции",
        current: "Проверить текущее состояние сеанса",
        noHistory:
          "Это ответ последнего создания. Для текущего серверного списка перейдите на вкладку «Текущие сеансы».",
        noElevation:
          "Здесь создаётся только обычный сеанс. Отзыв доступен на вкладке «Текущие сеансы» по серверной ревизии.",
        expired: "Время сеанса истекло. Текущее состояние сервера неизвестно.",
        sample: "В дизайн-превью кнопка не обращается к серверу.",
      }
    : {
        title: "Normal AgentSession",
        description:
          "Create a server-owned normal session in the selected project. This is not an elevation grant.",
        fixed: "Fixed permissions",
        requestable: "Allow elevation requests",
        label: "Session description (optional)",
        placeholder: "For example, source import",
        create: "Open session",
        opening: "Revalidating rights and opening session…",
        inactive: "Sign-in and Project access must be verified by the server",
        unavailable: "Session owner unavailable; no new session confirmed.",
        uncertain:
          "Creation response is unconfirmed. The original request is retained; no new session is created automatically.",
        retry: "Retry original request",
        recoveryExpired:
          "The original request recovery window elapsed. Check current sessions; no replacement is created automatically.",
        retained:
          "An unresolved request is retained. Retry keeps its key and payload after verifying current permissions again.",
        denied: "Server denied access to the selected project",
        signedOut: "Login session ended — sign in again",
        conflict: "Server state changed — refresh the permission proof",
        invalid: "Invalid request or unverified response from server",
        opened: "New normal session confirmed by the server",
        recovered: "Original creation result recovered",
        expires: "Expires",
        revision: "Revision",
        operations: "Allowed operations",
        current: "Inspect current session state",
        noHistory:
          "This is the last create response. Switch to Current sessions for the server-owned list.",
        noElevation:
          "Only a normal session is created here. Revocation is available from Current sessions with the server grant revision.",
        expired: "Session time elapsed. Current server state is unknown.",
        sample: "Design preview never invokes the server.",
      },
);
const {
  policy,
  label,
  busy,
  result,
  expired,
  recovered,
  inspectCurrent,
  outcomeKey,
  pending,
  eligible,
  create,
} = useSessionOpen(props, sessionCommands);
const outcome = computed(() => (outcomeKey.value ? words.value[outcomeKey.value] : ""));
</script>
<template>
  <Card class="min-w-0">
    <CardHeader>
      <CardTitle class="flex items-center gap-2 text-sm">
        <FolderKey class="size-4" aria-hidden="true" />{{ words.title }}
      </CardTitle>
      <p class="text-xs leading-5 text-muted-foreground">{{ words.description }}</p>
    </CardHeader>
    <CardContent class="space-y-4">
      <fieldset class="flex flex-wrap gap-2" :aria-label="words.title">
        <Button
          type="button"
          size="sm"
          :variant="policy === 'requestable' ? 'default' : 'outline'"
          :aria-pressed="policy === 'requestable'"
          :disabled="busy || pending !== null"
          @click="policy = 'requestable'"
          >{{
            words.requestable
          }}</Button
        >
        <Button
          type="button"
          size="sm"
          :variant="policy === 'fixed' ? 'default' : 'outline'"
          :aria-pressed="policy === 'fixed'"
          :disabled="busy || pending !== null"
          @click="policy = 'fixed'"
          >{{
            words.fixed
          }}</Button
        >
      </fieldset>
      <label :for="labelId" class="block max-w-md space-y-2 text-xs font-semibold">
        <span>{{ words.label }}</span>
        <Input
          :id="labelId"
          v-model="label"
          :disabled="busy || pending !== null"
          :placeholder="words.placeholder"
          maxlength="128"
          autocomplete="off"
        />
      </label>
      <p class="text-xs text-muted-foreground">
        {{ designPreview ? words.sample : words.noElevation }}
      </p>
      <Button :disabled="!eligible || pending !== null" @click="create(false)">
        <ShieldCheck class="mr-1 size-4" aria-hidden="true" />{{ words.create }}
      </Button>
      <div v-if="pending" class="space-y-2 rounded-lg border border-border p-3">
        <p class="text-xs leading-5 text-muted-foreground" role="status">{{ words.retained }}</p>
        <Button variant="outline" :disabled="!eligible" @click="create(true)">{{
          words.retry
        }}</Button>
      </div>
      <div v-if="busy" class="space-y-2" role="status">
        <p class="text-xs text-muted-foreground">{{ words.opening }}</p>
        <Skeleton class="h-10 w-full" />
      </div>
      <p
        v-if="outcome"
        class="rounded-lg border border-border bg-muted/30 p-3 text-sm text-foreground"
        role="alert"
      >
        {{ outcome }}
      </p>
      <p v-if="!eligible && !busy && !result" class="text-xs text-muted-foreground" role="status">
        {{ designPreview ? words.sample : words.inactive }}
      </p>
      <div
        v-if="result"
        class="space-y-3 rounded-xl border border-border bg-muted/20 p-4"
        role="status"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="text-sm font-semibold">
            {{ expired ? words.expired : recovered ? words.recovered : words.opened }}
          </p>
          <Badge variant="outline">{{
            result.elevation_policy === "fixed" ? words.fixed : words.requestable
          }}</Badge>
        </div>
        <p class="break-all font-mono text-xs">{{ result.session_uuid }}</p>
        <p class="text-xs text-muted-foreground">{{ words.revision }}: {{ result.revision }}</p>
        <p class="flex items-center gap-1 text-xs text-muted-foreground">
          <Clock3 class="size-4" aria-hidden="true" />{{ words.expires }}:
          {{ new Date(result.hard_expires_at).toLocaleString(locale) }}
        </p>
        <p class="text-xs">{{ words.operations }}: {{ result.operations.join(", ") }}</p>
        <p class="text-xs text-muted-foreground">{{ words.noHistory }}</p>
        <Button
          type="button"
          variant="outline"
          :disabled="!eligible"
          @click="inspectCurrent = !inspectCurrent"
          :aria-expanded="inspectCurrent"
          >{{
            words.current
          }}</Button
        >
        <SessionInspector
          v-if="inspectCurrent && projectId && actorId && proofExpiresAt"
          :key="result.session_uuid"
          :project-id="projectId"
          :session-id="result.session_uuid"
          :actor-id="actorId"
          :proof-expires-at="proofExpiresAt"
          :can-list="canOpen === true"
          :can-approve="canApprove === true"
        />
      </div>
    </CardContent>
  </Card>
</template>
