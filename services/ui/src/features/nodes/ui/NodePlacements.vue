<script setup lang="ts">
import { Button } from "@/shared/ui/button";
import {DataTable} from "@/shared/ui/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/shared/ui/dialog";
import EditorDialog from "@/shared/ui/EditorDialog.vue";
import { Input } from "@/shared/ui/input";
import StatusBadge from "@/shared/ui/StatusBadge.vue";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/shared/ui/select";
import PlacementConfiguration from "./PlacementConfiguration.vue";
import PlacementOperation from "./PlacementOperation.vue";
import PlacementStatusDetails from "./PlacementStatusDetails.vue";
import ProjectWorkspaceSelector from "./ProjectWorkspaceSelector.vue";
import RuntimePolicySettings from "./RuntimePolicySettings.vue";
import {useId} from "vue"
import {placementRecoveryStorage} from "../api/placement-recovery-storage"
import type {ManagedNode} from "@/entities/node"
import {nodeGateway} from "../api/nodes"
import {useNodePlacements} from "../model/use-node-placements"
import {moduleLabel,moduleName} from "../model/module-presentation"
import {placementStatus} from "../model/operation-presentation"
const formId=useId()
const props=defineProps<{ node: ManagedNode; projectId: string }>()
const emit=defineEmits<{close:[]}>()
const {rows,catalog,loading,busy,error,formError,editor,recovering,name,release,memory,cpu,pids,updating,configuration,workspaces,projectWorkspace,workspaceBusy,workspaceError,releases,artifact,selectedModule,releaseSections,valid,changed,open,openUpdate,place,recover,reconcile,ensureWorkspace}=useNodePlacements(props,nodeGateway,placementRecoveryStorage)
</script>
<template>
  <Dialog
    :open="true"
    @update:open="
      (value) => {
        if (!value && !busy) emit('close');
      }
    "
    ><DialogContent
      class="min-w-0 w-[calc(100vw-2rem)] max-w-[calc(100vw-2rem)] max-h-[90vh] overflow-y-auto sm:max-w-4xl [&>*]:min-w-0 [&>*]:max-w-full"
      ><DialogHeader class="min-w-0 max-w-full"
        ><DialogTitle>MCP: {{ node.name }}</DialogTitle>
        <RuntimePolicySettings :project-id="projectId" :node-id="node.id" />
        <DialogDescription class="whitespace-normal break-words"
          >Рабочая папка проекта общая для MCP этой ноды. Профили браузера и данные инфраструктуры
          хранятся отдельно.</DialogDescription
        ></DialogHeader
      >
      <div class="flex justify-end">
        <Button :disabled="!node.enabled || busy || !releases.length" @click="open"
          >Добавить MCP</Button
        >
      </div>
      <p v-if="error" role="alert" class="text-sm text-destructive">{{ error }}</p>
      <p v-if="!loading && !rows.length" class="text-sm text-muted-foreground">
        В этом проекте на ноде ещё нет размещённых MCP.
      </p>
      <DataTable
        class="min-w-0 max-w-full"
        :rows="rows"
        :loading="loading"
        label="MCP ноды"
        :search-text="
          (row) =>
            row.name +
            ' ' +
            moduleLabel(
              row.module,
              catalog.artifacts.find((item) => item.key === row.module)?.name ?? row.module,
            )
        "
        :columns="[
          { key: 'name', title: 'Название', dataIndex: 'name' },
          { key: 'moduleName', title: 'Модуль', dataIndex: 'module', defaultHidden: true },
          { key: 'state', title: 'Состояние' },
          { key: 'limits', title: 'Лимиты' },
          { key: 'actions', title: 'Операция' },
        ]"
      >
        <template #cell="{ row, column }">
          <div v-if="column.key === 'name'" class="min-w-0 max-w-36 [overflow-wrap:anywhere]">
            {{ row.name }}
          </div>
          <span v-else-if="column.key === 'moduleName'" class="break-words">{{
            moduleLabel(
              row.module,
              catalog.artifacts.find((item) => item.key === row.module)?.name ?? row.module,
            )
          }}</span>
          <template v-else-if="column.key === 'state'">
            <PlacementStatusDetails
              v-if="row.operation"
              :operation="row.operation"
              :state="row.state"
              :sequence="row.sequence"
              :name="row.name"
              ><Button
                type="button"
                variant="ghost"
                size="xs"
                class="h-auto min-w-0 p-0 hover:bg-transparent"
                :aria-label="
                  placementStatus(row.state, row.sequence).label +
                  '. Сведения о состоянии: ' +
                  row.name
                "
                ><StatusBadge
                  :label="placementStatus(row.state, row.sequence).label"
                  :tone="placementStatus(row.state, row.sequence).tone"
                /></Button
              ></PlacementStatusDetails
            >
            <StatusBadge
              v-else
              :label="placementStatus(row.state, row.sequence).label"
              :tone="placementStatus(row.state, row.sequence).tone"
            />
          </template>
          <div v-else-if="column.key === 'limits'" class="text-xs tabular-nums leading-4">
            <span class="block">{{ row.limits.memory_bytes / 1024 ** 2 }} MiB</span
            ><span class="block text-muted-foreground">{{ row.limits.cpu_millis / 1000 }} CPU</span>
          </div>
          <PlacementOperation
            v-else-if="column.key === 'actions'"
            :operation="row.operation"
            :state="row.state"
            :sequence="row.sequence"
            :module="row.module"
            :name="row.name"
            :busy="busy"
            :recovering="recovering === row.id"
            @edit="openUpdate(row)"
            @reconcile="reconcile(row)"
            @recover="recover(row)"
          />
        </template>
      </DataTable>
    </DialogContent></Dialog
  >
  <EditorDialog
    :open="editor"
    :title="updating ? 'Настроить размещение MCP' : 'Добавить MCP в проект'"
    :description="
      updating
        ? 'Изменения сборки, конфигурации или лимитов заменят только этот контейнер и завершат его активные сеансы. Рабочая папка сохранится.'
        : 'Нода загрузит одобренный образ и запустит один контейнер с указанными лимитами. Рабочая папка сохраняется отдельно от контейнера.'
    "
    :busy="busy"
    :disabled="!valid || !changed"
    :error="formError"
    :submit-label="updating ? 'Сохранить' : 'Запустить'"
    @update:open="(value) => (editor = value)"
    @submit="place"
  >
    <p v-if="updating && !release" role="alert" class="text-sm text-destructive">
      Текущая сборка отсутствует в каталоге. Выберите сборку явно.
    </p>
    <p v-else-if="updating && !changed" class="text-sm text-muted-foreground">
      Изменений нет. Контейнер продолжает работать.
    </p>
    <label class="block space-y-1 text-sm" :for="`${formId}-name`"
      >Название<Input
        v-model="name"
        :id="`${formId}-name`"
        :disabled="!!updating"
        maxlength="128"
      /></label
    >
    <label class="block space-y-1 text-sm" :for="`${formId}-release`"
      >Сборка<Select v-model="release"
        ><SelectTrigger :id="`${formId}-release`"><SelectValue /></SelectTrigger
        ><SelectContent
          ><SelectGroup v-for="section in releaseSections" :key="section.id"
            ><SelectLabel>{{ section.name }}</SelectLabel
            ><SelectItem v-for="item in section.releases" :key="item.id" :value="item.id"
              >{{
                moduleName(
                  item.module,
                  catalog.artifacts.find((artifact) => artifact.key === item.module)?.name ??
                    item.module,
                )
              }}
              · {{ item.source_commit.slice(0, 8) }} ·
              {{ item.image.split("@sha256:")[1]?.slice(0, 12) }}</SelectItem
            ></SelectGroup
          ></SelectContent
        ></Select
      ></label
    >
    <PlacementConfiguration
      v-if="['web', 'serena'].includes(selectedModule)"
      v-model="configuration"
      :module="selectedModule"
    />
    <ProjectWorkspaceSelector
      v-if="['web', 'reverse'].includes(selectedModule)"
      :read-only-required="selectedModule === 'reverse'"
      v-model="projectWorkspace"
      :workspaces="workspaces"
      :busy="workspaceBusy || busy"
      :error="workspaceError"
      @create="ensureWorkspace"
    />
    <label class="block space-y-1 text-sm" :for="`${formId}-memory`"
      >Память, MiB<Input v-model="memory" :id="`${formId}-memory`" type="number" min="64" /></label
    >
    <label class="block space-y-1 text-sm" :for="`${formId}-cpu`"
      >CPU, тысячные доли ядра<Input
        v-model="cpu"
        :id="`${formId}-cpu`"
        type="number"
        min="100"
      /></label
    >
    <label class="block space-y-1 text-sm" :for="`${formId}-pids`"
      >Лимит процессов<Input v-model="pids" :id="`${formId}-pids`" type="number" min="32" /></label
    >
  </EditorDialog>
</template>
