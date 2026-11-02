<script setup lang="ts">
import { AlertCircle, Clock } from "lucide-vue-next";

import { computed, useId, watch } from "vue";
import { useI18n } from "vue-i18n";
import {
  type CurrentSessionsViewContext,
  isCurrentSessionId,
  SessionInspector,
  sessionCommands,
  useCurrentSessions,
} from "@/features/agent-sessions";
import { Badge } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import ConfirmationDialog from "@/shared/ui/ConfirmationDialog.vue";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/card";
import type { ActivitySnapshot } from "@/shared/ui/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/shared/ui/dialog";
import { Input } from "@/shared/ui/input";
import { Skeleton } from "@/shared/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/shared/ui/table";
import { type SessionActivityContext, sessionActivityRow } from "../model/activity-rows";

const lookupControlId = useId();
const sessionFilters = ["all", "active", "revoked", "expired"] as const;
const props = withDefaults(defineProps<CurrentSessionsViewContext>(), {
  designPreview: false,
  previewState: "empty",
});
const emit = defineEmits<{ snapshot: [value: ActivitySnapshot] }>();
const { locale } = useI18n();
const msg = computed(() =>
  locale.value === "ru"
    ? {
        heading: "Текущие AgentSession",
        source: "Серверные сеансы выбранного проекта, текущая ревизия и операции",
        all: "Все",
        active: "Активные",
        revoked: "Отозваны",
        expired: "Истекли",
        id: "Сеанс",
        operations: "Операции",
        status: "Состояние",
        revision: "Ревизия",
        scope: "Ресурсы",
        expires: "Срок",
        actions: "Действия",
        actor: "Инициатор",
        elevated: "Расширенный",
        normal: "Обычный",
        inspect: "Подробнее",
        detail: "Текущий AgentSession",
        detailSource: "Отдельное серверное чтение выбранного сеанса",
        lookup: "Открыть сеанс по ID",
        lookupLabel: "ID AgentSession",
        lookupHint: "Точное чтение в выбранном проекте, включая сеансы вне загруженного списка.",
        lookupInvalid: "Введите канонический UUIDv4 сеанса",
        recoverTarget: "Проверить исходный сеанс",
        observed:
          "Ответ команды потерян. Показано текущее состояние сеанса по отдельному чтению, а не подтверждение выполнения этой команды.",
        proofExpired: "Подтверждение доступа к проекту истекло",
        refresh: "Обновить",
        search: "Поиск по ID, инициатору и операции",
        empty: "Подтверждённых сеансов пока нет",
        noMatch: "В загруженном списке нет сеансов по выбранным фильтрам",
        clearFilter: "Сбросить фильтры",
        stale: "Срок сеанса истёк. Обновляем состояние автоматически…",
        loading: "Получаем текущие сеансы и ревизии…",
        idle: "Для просмотра нужен действующий серверный доступ к проекту",
        unauthorized: "Сеанс входа завершён; требуется повторная авторизация",
        denied: "Сервер не подтвердил доступ к сеансам проекта",
        invalid: "Некорректное подтверждение сеансов от Backend",
        unavailable: "История сеансов временно недоступна; никаких действий выполнять нельзя",
        revoke: "Отозвать",
        review: "Проверить отзыв сеанса",
        confirm: "Подтвердить отзыв",
        cancel: "Отмена",
        warning:
          "Отзыв требует действующего полномочия approver и текущей ревизии гранта. Действие нельзя отменить.",
        uncertainty:
          "Сервер не подтвердил окончательный результат отзыва. Перед повторной операцией обновите список.",
        conflict: "Ревизия сеанса изменилась. Список обновлён; проверьте состояние.",
        failure: "Отзыв запрещён или не подтверждён сервером.",
        success: "Отзыв подтверждён повторным чтением состояния сервера.",
        elevationBlocked:
          "Повышение полномочий требует выбранных серверно подтверждённых ресурсов и операции; произвольные scope не отправляются.",
      }
    : {
        heading: "Current AgentSessions",
        source: "Server-owned Project sessions, current revisions and operations",
        all: "All",
        active: "Active",
        revoked: "Revoked",
        expired: "Expired",
        id: "Session",
        operations: "Operations",
        status: "Status",
        revision: "Revision",
        scope: "Resources",
        expires: "Expiry",
        actions: "Actions",
        actor: "Created by",
        elevated: "Elevated",
        normal: "Normal",
        inspect: "Details",
        detail: "Current AgentSession",
        detailSource: "Independent server read of the selected session",
        lookup: "Open session by ID",
        lookupLabel: "AgentSession ID",
        lookupHint:
          "Exact read within the selected Project, including sessions outside the loaded list.",
        lookupInvalid: "Enter a canonical session UUIDv4",
        recoverTarget: "Inspect original session",
        observed:
          "Command reply was lost. The separate read shows current session state, not proof that this command completed.",
        proofExpired: "Project access proof expired",
        refresh: "Refresh",
        search: "Find by ID, actor or operation",
        empty: "No server-confirmed sessions",
        noMatch: "No loaded sessions match these filters",
        clearFilter: "Clear filters",
        stale: "A session expired. Updating its state automatically…",
        loading: "Loading current sessions and grant revisions…",
        idle: "Current Project access required to view sessions",
        unauthorized: "Login session ended; sign in again",
        denied: "Server did not verify access to Project sessions",
        invalid: "Backend returned invalid session evidence",
        unavailable: "Session inventory unavailable; actions are disabled",
        revoke: "Revoke",
        review: "Review session revocation",
        confirm: "Confirm revoke",
        cancel: "Cancel",
        warning:
          "Revocation requires current approver permission and grant revision. This action cannot be undone.",
        uncertainty:
          "Server did not verify revocation outcome. Refresh before attempting another operation.",
        conflict: "Session revision changed. List refreshed; review current state.",
        failure: "Revocation was denied or unconfirmed by the server.",
        success: "Revocation confirmed by reading the exact current session.",
        elevationBlocked:
          "Elevation requires verified resource selectors and effects; arbitrary scopes are never sent.",
      },
);
const {
  items,
  filtering,
  search,
  busy,
  refreshing,
  errorKey,
  infoKey,
  confirmation,
  inspecting,
  lookupId,
  lookupOpen,
  lastTarget,
  canFetch,
  shown,
  currentStatus,
  actionAllowed,
  lookup,
  requestRevoke,
  confirmRevoke,
} = useCurrentSessions(props, sessionCommands);
const error = computed(() => (errorKey.value ? msg.value[errorKey.value] : ""));
const info = computed(() => (infoKey.value ? msg.value[infoKey.value] : ""));
const statusText = computed(() =>
  currentStatus.value === "ready"
    ? items.value.length
      ? msg.value.noMatch
      : msg.value.empty
    : msg.value[currentStatus.value],
);
const activityContext = computed<SessionActivityContext>(() => ({
  actorId: props.actorId,
  actorNames: props.actorNames,
  locale: locale.value,
  pending: busy.value || refreshing.value,
  labels: msg.value,
  canInspect: () => canFetch.value && !busy.value && !refreshing.value,
  inspect: (id) => {
    inspecting.value = id;
  },
  canRevoke: actionAllowed,
  requestRevoke,
}));
const tableSnapshot = computed<ActivitySnapshot>(() => ({
  rows:
    currentStatus.value === "ready" && canFetch.value
      ? items.value.map((item) => sessionActivityRow(item, activityContext.value))
      : [],
  loading: refreshing.value || currentStatus.value === "loading",
  message:
    error.value ||
    info.value ||
    (currentStatus.value !== "ready" && currentStatus.value !== "loading" ? statusText.value : ""),
}));
watch(tableSnapshot, (value) => emit("snapshot", value), { immediate: true });
defineExpose({
  openLookup: () => {
    lookupOpen.value = true;
  },
});
</script>

<template>
  <Card v-if="!renderless" class="min-w-0">
    <CardHeader class="flex flex-row flex-wrap items-start justify-between gap-3">
      <div class="space-y-1">
        <CardTitle class="text-sm">{{ msg.heading }}</CardTitle>
        <p class="text-xs leading-5 text-muted-foreground">{{ msg.source }}</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <Button
          variant="ghost"
          size="sm"
          :disabled="!canFetch || busy"
          @click="lookupOpen = true"
          >{{
            msg.lookup
          }}</Button
        >
      </div>
    </CardHeader>
    <CardContent class="min-w-0 space-y-4">
      <fieldset class="flex flex-wrap gap-2" :aria-label="msg.status">
        <Button
          v-for="filter in sessionFilters"
          :key="filter"
          type="button"
          size="sm"
          :variant="filtering === filter ? 'default' : 'outline'"
          :aria-pressed="filtering === filter"
          @click="filtering = filter"
          >{{
            msg[filter]
          }}</Button
        >
        <Input
          v-model="search"
          class="w-full sm:ml-auto sm:w-64"
          :placeholder="msg.search"
          :aria-label="msg.search"
          maxlength="128"
        />
        <Button
          v-if="search || filtering !== 'all'"
          variant="ghost"
          size="sm"
          @click="
            search = '';
            filtering = 'all';
          "
          >{{
            msg.clearFilter
          }}</Button
        >
      </fieldset>
      <p
        v-if="error"
        role="alert"
        class="flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-sm text-destructive"
      >
        <AlertCircle class="mt-0.5 size-4 shrink-0" aria-hidden="true" />{{ error }}
      </p>
      <p v-if="info" role="status" class="rounded-lg border border-border bg-muted/20 p-3 text-sm">
        {{ info }}
      </p>
      <div v-if="currentStatus === 'loading'" class="space-y-3" role="status">
        <Skeleton v-for="i in 3" :key="i" class="h-11 w-full" />
      </div>
      <p
        v-else-if="currentStatus !== 'ready' || !shown.length"
        role="status"
        class="rounded-xl border border-dashed border-border px-4 py-10 text-center text-sm text-muted-foreground"
      >
        {{ statusText }}
      </p>
      <div v-else class="min-w-0 overflow-x-auto rounded-xl border border-border">
        <Table class="min-w-[650px] text-sm">
          <TableHeader>
            <TableRow>
              <TableHead>{{ msg.id }}</TableHead>
              <TableHead>{{ msg.actor }}</TableHead>
              <TableHead>{{ msg.operations }}</TableHead>
              <TableHead>{{ msg.status }}</TableHead>
              <TableHead>{{ msg.actions }}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="session in shown" :key="session.session_uuid">
              <TableCell class="max-w-32"
                ><p class="text-xs">{{ session.is_elevated ? msg.elevated : msg.normal }}</p>
                <span
                  class="font-mono text-[11px] text-muted-foreground"
                  :title="session.session_uuid"
                  >{{
                    session.session_uuid.slice(0, 8)
                  }}</span
                ></TableCell
              >
              <TableCell class="max-w-40 text-xs" :title="session.created_by_user_uuid">{{
                actorNames?.[session.created_by_user_uuid] ||
                (session.created_by_user_uuid === actorId ? "Вы" : "Пользователь")
              }}</TableCell>
              <TableCell class="min-w-32 max-w-60 text-xs">
                <p v-for="operation in session.operations" :key="operation">{{ operation }}</p>
                <details v-if="session.resources.length" class="mt-2 text-muted-foreground">
                  <summary class="cursor-pointer">
                    {{ msg.scope }}: {{ session.resources.length }}
                  </summary>
                  <p
                    v-for="(scope, i) in session.resources"
                    :key="i"
                    class="mt-1 break-all font-mono text-[11px]"
                  >
                    {{ scope.hand }} · {{ scope.tool }} · {{ scope.resource.kind }}:
                    {{ scope.resource.id }}
                  </p>
                </details>
              </TableCell>
              <TableCell class="min-w-32 text-xs">
                <Badge variant="outline">{{ msg[session.status] }}</Badge>
                <p class="mt-2">{{ session.is_elevated ? msg.elevated : msg.normal }}</p>
                <p class="mt-1 flex items-center gap-1 text-muted-foreground">
                  <Clock class="size-3" aria-hidden="true" />
                  {{ new Date(session.hard_expires_at).toLocaleString(locale) }}
                </p>
              </TableCell>
              <TableCell class="space-y-1">
                <Button
                  variant="outline"
                  size="sm"
                  :disabled="busy || refreshing || !canFetch"
                  @click="inspecting = session.session_uuid"
                  >{{
                    msg.inspect
                  }}</Button
                >
                <Button
                  v-if="actionAllowed(session)"
                  variant="outline"
                  size="sm"
                  @click="requestRevoke(session)"
                  >{{
                    msg.revoke
                  }}</Button
                >
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
      <p class="text-xs leading-5 text-muted-foreground">{{ msg.elevationBlocked }}</p>
    </CardContent>
  </Card>
  <Dialog :open="lookupOpen" @update:open="(value) => (lookupOpen = value)"
    ><DialogContent
      ><DialogHeader
        ><DialogTitle>{{ msg.lookup }}</DialogTitle
        ><DialogDescription>{{ msg.lookupHint }}</DialogDescription></DialogHeader
      >
      <form class="space-y-3" @submit.prevent="lookup">
        <label :for="lookupControlId" class="block text-xs font-medium"
          ><span>{{ msg.lookupLabel }}</span>
          <Input
            :id="lookupControlId"
            v-model="lookupId"
            class="mt-2"
            maxlength="64"
            autocomplete="off"
            :disabled="!canFetch || busy"
          />
        </label>
        <p
          v-if="lookupId && !isCurrentSessionId(lookupId.trim())"
          class="text-xs text-muted-foreground"
          role="status"
        >
          {{ msg.lookupInvalid }}
        </p>
        <Button
          type="submit"
          variant="outline"
          size="sm"
          :disabled="
            designPreview || !canFetch || busy || refreshing || !isCurrentSessionId(lookupId.trim())
          "
          >{{
            msg.lookup
          }}</Button
        >
        <Button
          v-if="lastTarget"
          type="button"
          variant="outline"
          size="sm"
          :disabled="!canFetch || busy || refreshing"
          @click="inspecting = lastTarget"
          >{{
            msg.recoverTarget
          }}</Button
        >
      </form></DialogContent
    ></Dialog
  >
  <Dialog
    :open="inspecting !== null"
    @update:open="
      (open) => {
        if (!open) inspecting = null;
      }
    "
  >
    <DialogContent class="max-h-[85vh] overflow-y-auto">
      <DialogHeader
        ><DialogTitle>{{ msg.detail }}</DialogTitle
        ><DialogDescription>{{ msg.detailSource }}</DialogDescription></DialogHeader
      >
      <SessionInspector
        v-if="inspecting && projectId && actorId && proofExpiresAt"
        :key="inspecting"
        :project-id="projectId"
        :session-id="inspecting"
        :actor-id="actorId"
        :proof-expires-at="proofExpiresAt"
        :can-list="canList === true"
        :can-approve="canApprove === true"
      />
    </DialogContent>
  </Dialog>
  <ConfirmationDialog
    :open="confirmation !== null"
    :title="msg.review"
    :description="msg.warning"
    :confirm-label="msg.confirm"
    :busy="busy"
    :disabled="!confirmation || !actionAllowed(confirmation)"
    @update:open="
      (value) => {
        if (!value) confirmation = null;
      }
    "
    @confirm="confirmRevoke"
  >
    <div v-if="confirmation" class="space-y-2 text-sm">
      <p class="break-all font-mono text-xs">{{ confirmation.session_uuid }}</p>
      <p>{{ msg.revision }}: {{ confirmation.revision }}</p>
      <p>{{ msg.operations }}: {{ confirmation.operations.join(", ") }}</p>
    </div>
  </ConfirmationDialog>
</template>
