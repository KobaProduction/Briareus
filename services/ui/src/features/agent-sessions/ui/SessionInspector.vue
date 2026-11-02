<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { Badge } from "@/shared/ui/badge";
import { Skeleton } from "@/shared/ui/skeleton";
import { readCurrentSession } from "../api/current-sessions";
import { type SessionInspectorContext, useSessionInspector } from "../model/use-session-inspector";

const props = defineProps<SessionInspectorContext>();
const { state, item } = useSessionInspector(props, readCurrentSession);
const { locale } = useI18n();
const words = computed(() =>
  locale.value === "ru"
    ? {
        refresh: "Обновить сеанс",
        loading: "Читаем текущий сеанс…",
        unauthorized: "Вход не подтверждён. Авторизуйтесь повторно.",
        not_found: "Сеанс не найден в доступной области проекта. Это не подтверждение отзыва.",
        forbidden: "Нет права читать этот сеанс.",
        invalid: "Сервер вернул неподтверждённый сеанс.",
        unavailable: "Текущее состояние сеанса недоступно; отсутствие ответа не означает отзыв.",
        expired: "Подтверждение доступа к проекту истекло.",
        stale: "Срок активного снимка сеанса истёк. Обновите состояние у сервера.",
        project: "Проект",
        creator: "Инициатор",
        revision: "Ревизия",
        expires: "Истекает",
        operations: "Операции",
        resources: "Точные области ресурсов",
        empty: "Области ресурсов не выданы",
        active: "Активен",
        revoked: "Отозван",
        expiredSession: "Истёк",
        normal: "Обычный",
        elevated: "Расширенный",
        note: "Это серверный снимок сеанса, не разрешение выполнить Files или другой MCP Hand.",
      }
    : {
        refresh: "Refresh session",
        loading: "Reading current session…",
        not_found:
          "Session not found in the accessible Project scope. This does not prove revocation.",
        unauthorized: "Sign-in is not verified. Sign in again.",
        forbidden: "Session read access denied.",
        invalid: "Server returned unverified session data.",
        unavailable:
          "Current session state is unavailable; a missing response does not prove revocation.",
        stale: "The active session snapshot expired. Refresh the server state.",
        expired: "Project access proof expired.",
        project: "Project",
        creator: "Created by",
        revision: "Revision",
        expires: "Expires",
        operations: "Operations",
        resources: "Exact resource scopes",
        empty: "No resource scopes granted",
        active: "Active",
        revoked: "Revoked",
        expiredSession: "Expired",
        normal: "Normal",
        elevated: "Elevated",
        note: "This is a server session snapshot, not a permit to execute Files or another MCP Hand.",
      },
);
</script>
<template>
  <section class="min-w-0 space-y-4" aria-live="polite">
    <div v-if="state === 'loading'" class="space-y-2" role="status">
      <p class="text-sm">{{ words.loading }}</p>
      <Skeleton class="h-20 w-full" />
    </div>
    <p
      v-else-if="state !== 'ready'"
      class="rounded-lg border border-border p-3 text-sm text-muted-foreground"
      role="status"
    >
      {{ words[state] }}
    </p>
    <div v-else-if="item" class="space-y-3">
      <p class="break-all font-mono text-xs">{{ item.session_uuid }}</p>
      <div class="flex flex-wrap gap-2">
        <Badge variant="outline">{{
          item.status === "expired" ? words.expiredSession : words[item.status]
        }}</Badge><Badge variant="outline">{{
          item.is_elevated ? words.elevated : words.normal
        }}</Badge>
      </div>
      <p v-if="item.label" class="whitespace-pre-wrap break-words text-sm">{{ item.label }}</p>
      <dl class="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2 text-xs">
        <dt>{{ words.project }}</dt>
        <dd class="break-all font-mono">{{ item.project_uuid }}</dd>
        <dt>{{ words.creator }}</dt>
        <dd class="break-all font-mono">{{ item.created_by_user_uuid }}</dd>
        <dt>{{ words.revision }}</dt>
        <dd>{{ item.revision }}</dd>
        <dt>{{ words.expires }}</dt>
        <dd>{{ new Date(item.hard_expires_at).toLocaleString(locale) }}</dd>
      </dl>
      <h4 class="text-sm font-semibold">{{ words.operations }}</h4>
      <p v-for="operation in item.operations" :key="operation" class="break-all font-mono text-xs">
        {{ operation }}
      </p>
      <h4 class="text-sm font-semibold">{{ words.resources }}</h4>
      <p v-if="!item.resources.length" class="text-xs text-muted-foreground">{{ words.empty }}</p>
      <p v-for="(scope, index) in item.resources" :key="index" class="break-all font-mono text-xs">
        {{ scope.hand }} · {{ scope.tool }} · {{ scope.action }} · {{ scope.resource.kind }}:
        {{ scope.resource.id }}
      </p>
      <p class="text-xs leading-5 text-muted-foreground">{{ words.note }}</p>
    </div>
  </section>
</template>
