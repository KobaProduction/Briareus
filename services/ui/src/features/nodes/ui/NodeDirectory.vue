<script setup lang="ts">
import { Plus, Server } from "lucide-vue-next";
import { Badge } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import ConfirmationDialog from "@/shared/ui/ConfirmationDialog.vue";
import {DataTable} from "@/shared/ui/data-table";
import EditorDialog from "@/shared/ui/EditorDialog.vue";
import { Input } from "@/shared/ui/input";
import RowActions from "@/shared/ui/RowActions.vue";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/shared/ui/select";
import ModuleCatalog from "./ModuleCatalog.vue";
import NodeEnrollment from "./NodeEnrollment.vue";
import NodePlacements from "./NodePlacements.vue";
import {useId} from "vue"
import type {VerifiedPlatformContext} from "@/entities/workspace"
import {nodeGateway} from "../api/nodes"
import {useNodeDirectory} from "../model/use-node-directory"
const formId=useId()
const props=defineProps<{ context: VerifiedPlatformContext; projectId: string | null }>()
const {project,operator,rows,error,loading,busy,editor,disable,enrollment,catalog,placementNode,name,endpoint,hostUuid,runtimeUid,memoryMb,cpuMillis,pids,scope,formError,valid,open,openDisable,save,confirmDisable,scopeName,refresh}=useNodeDirectory(props,nodeGateway)
</script>
<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="flex items-center gap-2 text-xl font-semibold"><Server class="size-5" />Ноды</h2>
        <p class="mt-1 text-sm text-muted-foreground">Серверы исполнения MCP и их ресурсы</p>
      </div>
      <Button v-if="operator" :disabled="!project" @click="open('register')"
        ><Plus class="mr-2 size-4" />Зарегистрировать ноду</Button
      >
    </div>
    <p v-if="!operator" class="text-sm text-muted-foreground">
      Управление нодами доступно системному оператору.
    </p>
    <p v-else-if="!project" class="text-sm text-muted-foreground">
      Для регистрации выберите доступный проект. Ноды учитываются отдельно от проекта.
    </p>
    <template v-else
      ><p v-if="error" role="alert" class="text-sm text-destructive">{{ error }}</p>
      <DataTable
        :rows="rows"
        :loading="loading"
        label="Ноды"
        :columns="[
          { key: 'name', title: 'Название', dataIndex: 'name' },
          { key: 'scope', title: 'Область', dataIndex: 'scope' },
          { key: 'state', title: 'Состояние' },
          { key: 'endpoint', title: 'Адрес', dataIndex: 'endpoint' },
          { key: 'actions', title: 'Действия' },
        ]"
      >
        <template #cell="{ row, column }"
          ><span v-if="column.key === 'scope'">{{ scopeName(row.scope) }}</span
          ><Badge v-else-if="column.key === 'state'" variant="outline">{{
            row.enabled ? "Включена" : row.paired ? "Подключена, отключена" : "Ожидает подключения"
          }}</Badge><RowActions
            v-else-if="column.key === 'actions'"
            :label="`Действия с нодой ${row.name}`"
            ><Button variant="ghost" class="w-full justify-start" @click="placementNode = row"
              >MCP проекта</Button
            ><Button
              variant="ghost"
              class="w-full justify-start"
              @click="enrollment = { node: row, action: 'setup' }"
              >Параметры установки</Button
            ><Button
              v-if="!row.paired"
              variant="ghost"
              class="w-full justify-start"
              @click="enrollment = { node: row, action: 'pair' }"
              >Подключить ноду</Button
            ><Button
              v-else-if="!row.enabled"
              variant="ghost"
              class="w-full justify-start"
              @click="enrollment = { node: row, action: 'enable' }"
              >Включить ноду</Button
            ><Button
              v-if="row.paired"
              variant="ghost"
              class="w-full justify-start"
              @click="open('budget', row)"
              >Ресурсы ноды</Button
            ><Button variant="ghost" class="w-full justify-start" @click="open('rename', row)"
              >Переименовать</Button
            ><Button
              variant="ghost"
              class="w-full justify-start text-destructive"
              :disabled="!row.enabled"
              @click="openDisable(row)"
              >Отключить</Button
            ></RowActions
          ><span v-else>{{
            column.key === "name" ? row.name : column.key === "endpoint" ? row.endpoint : ""
          }}</span></template
        >
      </DataTable>
      <p class="text-xs text-muted-foreground">
        Регистрация создаёт отключённую запись. После установки подтвердите публичный ключ и
        включите ноду. Подключение MCP проверяется отдельно.
      </p>
    </template>
    <NodeEnrollment
      v-if="enrollment && project"
      :node="enrollment.node"
      :action="enrollment.action"
      :project-id="project.id"
      @changed="refresh"
      @close="enrollment = null"
    />
    <Button v-if="operator && project" variant="outline" @click="catalog = true">Образы MCP</Button>
    <ModuleCatalog
      v-if="catalog && project"
      :key="project.id"
      :project-id="project.id"
      @close="catalog = false"
    />
    <NodePlacements
      v-if="placementNode && project"
      :key="project.id + placementNode.id"
      :node="placementNode"
      :project-id="project.id"
      @close="placementNode = null"
    />
    <EditorDialog
      :open="editor !== null"
      :title="
        editor === 'budget'
          ? 'Ресурсы ноды'
          : editor === 'rename'
            ? 'Переименовать ноду'
            : 'Регистрация ноды'
      "
      :description="
        editor === 'budget'
          ? 'Рабочий бюджет применяется без перезапуска MCP, в пределах подготовленной ёмкости сервера.'
          : 'Запись ноды и её выделенный runtime. Регистрация сама по себе не запускает контейнеры.'
      "
      :busy="busy"
      :disabled="!valid"
      :error="formError"
      @update:open="
        (value) => {
          if (!value) editor = null;
        }
      "
      @submit="save"
    >
      <label v-if="editor !== 'budget'" class="block space-y-1 text-sm" :for="`${formId}-name`"
        >Название<Input v-model="name" :id="`${formId}-name`" maxlength="128" /></label
      >
      <template v-if="editor === 'register'"
        ><label class="block space-y-1 text-sm" :for="`${formId}-scope`"
          >Область<Select v-model="scope"
            ><SelectTrigger :id="`${formId}-scope`"><SelectValue /></SelectTrigger
            ><SelectContent
              ><SelectItem value="shared">Общая</SelectItem
              ><SelectItem value="personal">Личная</SelectItem
              ><SelectItem value="team" :disabled="project?.owner.kind !== 'team'"
                >Командная — текущая команда проекта</SelectItem
              ></SelectContent
            ></Select
          ></label
        ><label class="block space-y-1 text-sm" :for="`${formId}-endpoint`"
          >HTTPS-адрес ноды<Input
            v-model="endpoint"
            :id="`${formId}-endpoint`"
            placeholder="https://node.example.com"
          /></label
        ><label class="block space-y-1 text-sm" :for="`${formId}-hostUuid`"
          >UUID хоста из конфигурации установки<Input
            v-model="hostUuid"
            :id="`${formId}-hostUuid`"
          /></label
        ><label class="block space-y-1 text-sm" :for="`${formId}-runtimeUid`"
          >Выделенный UID runtime<Input
            v-model="runtimeUid"
            :id="`${formId}-runtimeUid`"
            type="number"
            min="2000"
          /></label
        ></template
      ><template v-if="editor === 'register' || editor === 'budget'">
        <label class="block space-y-1 text-sm" :for="`${formId}-memoryMb`"
          >Общая память, MiB<Input
            v-model="memoryMb"
            :id="`${formId}-memoryMb`"
            type="number"
            min="512"
          /></label
        >
        <label class="block space-y-1 text-sm" :for="`${formId}-cpuMillis`"
          >Общий CPU, millicores<Input
            v-model="cpuMillis"
            :id="`${formId}-cpuMillis`"
            type="number"
            min="751"
          /></label
        >
        <label class="block space-y-1 text-sm" :for="`${formId}-pids`"
          >Лимит процессов<Input
            v-model="pids"
            :id="`${formId}-pids`"
            type="number"
            min="193"
          /></label
        >
        <p class="text-xs text-muted-foreground">
          Резерв контроллера и Gateway — минимум 384 MiB, 750 millicores и 192 процесса. Изменение
          ограничено ёмкостью, подготовленной bootstrap на сервере, и уже выделенными ресурсами MCP.
        </p>
      </template>
    </EditorDialog>
    <ConfirmationDialog
      :open="!!disable"
      title="Отключить ноду?"
      description="Новые обращения к MCP этой ноды будут закрыты. Рабочие данные не удаляются."
      confirm-label="Отключить"
      :busy="busy"
      danger
      @update:open="
        (value) => {
          if (!value) disable = null;
        }
      "
      @confirm="confirmDisable"
    />
  </div>
</template>
