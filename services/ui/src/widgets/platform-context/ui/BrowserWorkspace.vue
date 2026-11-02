<script setup lang="ts">
import {
  ArrowLeft,
  ArrowRight,
  List,
  LockKeyhole,
  LockKeyholeOpen,
  Monitor,
  MoreHorizontal,
  Plus,
  Puzzle,
  RotateCcw,
  RotateCw,
  Settings,
  X,
} from "lucide-vue-next";
import { useId } from "vue";
import { editableBrowserElement, transportLabel } from "@/entities/browser";
import type { VerifiedPlatformContext } from "@/entities/workspace";
import {
  createProjectBrowser,
  ProjectBrowserSurface,
  useProjectBrowserWorkspace,
} from "@/features/project-browser";
import { readHandResources } from "@/shared/events";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/shared/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/shared/ui/select";

const formId = useId();
const props = defineProps<{ context: VerifiedPlatformContext; selectedProjectId: string | null }>();
defineEmits<{ selectProject: [id: string]; openSessions: [] }>();
const {
  project,
  tabs,
  tabId,
  draft,
  addressEditing,
  notice,
  busy,
  canReopen,
  menuOpen,
  tabsOpen,
  snapshot,
  preview,
  zoom,
  width,
  height,
  inputValues,
  current,
  allowed,
  elements,
  selectTab,
  navigate,
  closeTab,
  browserMenu,
  queueBrowserInputs,
  pageAction,
  resize,
  interact,
} = useProjectBrowserWorkspace(props, {
  resources: (project, signal) =>
    readHandResources("browser.resources", project, ["web.access"], signal),
  client: createProjectBrowser,
});
function browserShortcut(event: KeyboardEvent): void {
  if (!(event.ctrlKey || event.metaKey)) return;
  const key = event.key.toLowerCase();
  if (!["t", "l"].includes(key)) return;
  event.preventDefault();
  if (key === "l" && event.currentTarget instanceof HTMLElement) {
    const address = event.currentTarget.querySelector('input[aria-label="Адрес страницы"]');
    if (address instanceof HTMLInputElement) {
      address.focus();
      address.select();
    }
    return;
  }
  if (busy.value || !allowed.value) return;
  if (event.shiftKey) browserMenu("restore");
  else navigate(true);
}
</script>
<template>
  <section
    role="application"
    aria-label="Браузер проекта"
    class="min-w-0 space-y-3"
    @keydown="browserShortcut"
  >
    <p v-if="project && !project.permissions.includes('use_resources')" role="status">
      У вас нет права использовать ресурсы этого проекта.
    </p>
    <div class="overflow-hidden rounded-xl border border-border/70 bg-card shadow-sm">
      <div class="flex h-11 items-end gap-1 border-b border-border/70 bg-muted/60 px-2 pt-1">
        <Popover v-model:open="tabsOpen">
          <PopoverTrigger as-child>
            <Button
              variant="ghost"
              size="icon"
              class="mb-1 size-7 shrink-0"
              aria-label="Все вкладки"
              :disabled="!tabs.length"
            >
              <List class="size-4" />
            </Button>
          </PopoverTrigger>
          <PopoverContent align="start" class="max-h-80 w-80 overflow-auto p-1">
            <Button
              v-for="tab in tabs"
              :key="tab.page_id"
              variant="ghost"
              class="h-auto w-full justify-start px-2 py-2 text-left"
              :disabled="busy"
              @click="selectTab(tab.page_id)"
            >
              <span class="min-w-0">
                <span class="block truncate text-sm">{{
                  tab.title || tab.label || "Новая вкладка"
                }}</span>
                <span class="block truncate text-xs text-muted-foreground">{{ tab.url }}</span>
              </span>
            </Button>
          </PopoverContent>
        </Popover>
        <div
          role="tablist"
          aria-label="Вкладки браузера"
          class="flex min-w-0 flex-1 gap-1 overflow-x-auto"
        >
          <div
            v-for="tab in tabs"
            :key="tab.page_id"
            class="group flex h-9 min-w-32 max-w-56 flex-1 items-center rounded-t-lg border border-transparent"
            :class="
              tabId === tab.page_id
                ? 'border-border/70 border-b-card bg-card'
                : 'text-muted-foreground hover:bg-accent/70'
            "
          >
            <button
              type="button"
              role="tab"
              :id="`${formId}-tab-${tab.page_id}`"
              :aria-selected="tabId === tab.page_id"
              :aria-controls="`${formId}-page`"
              :disabled="busy"
              class="min-w-0 flex-1 truncate px-3 py-2 text-left text-xs"
              :title="tab.url"
              @click="selectTab(tab.page_id)"
            >
              {{ tab.title || tab.label || "Новая вкладка" }}
            </button>
            <Button
              size="icon"
              variant="ghost"
              class="mr-1 size-6 shrink-0"
              :disabled="busy || !allowed"
              :aria-label="`Закрыть вкладку ${tab.title || tab.label || 'без названия'}`"
              @click.stop="closeTab(tab.page_id)"
            >
              <X class="size-3" />
            </Button>
          </div>
        </div>
        <Button
          size="icon"
          variant="ghost"
          class="mb-1 size-7 shrink-0"
          :disabled="busy || !allowed"
          aria-label="Новая вкладка"
          @click="navigate(true)"
          ><Plus class="size-4" /></Button
        >
      </div>

      <form
        class="flex min-w-0 items-center gap-1 border-b border-border/70 px-2 py-1.5"
        @submit.prevent="navigate(false)"
      >
        <Button
          type="button"
          size="icon"
          variant="ghost"
          class="size-8 shrink-0"
          :disabled="busy || !allowed || !tabId"
          aria-label="Назад"
          @click="pageAction('local_browser_back')"
          ><ArrowLeft class="size-4" /></Button
        >
        <Button
          type="button"
          size="icon"
          variant="ghost"
          class="size-8 shrink-0"
          :disabled="busy || !allowed || !tabId"
          aria-label="Вперёд"
          @click="pageAction('local_browser_forward')"
          ><ArrowRight class="size-4" /></Button
        >
        <Button
          type="button"
          size="icon"
          variant="ghost"
          class="size-8 shrink-0"
          :disabled="busy || !allowed || !tabId"
          aria-label="Перезагрузить страницу"
          @click="pageAction('local_browser_reload')"
          ><RotateCw class="size-4" /></Button
        >
        <div
          class="mx-1 flex min-w-0 flex-1 items-center rounded-full border border-border/70 bg-muted/55 px-3 focus-within:border-ring"
        >
          <component
            :is="current?.url.startsWith('https:') ? LockKeyhole : LockKeyholeOpen"
            class="mr-2 size-3.5 shrink-0 text-muted-foreground"
            :title="transportLabel(current?.url ?? '')"
          />
          <Input
            v-model="draft"
            @focus="addressEditing = true"
            @blur="addressEditing = false"
            class="h-8 min-w-0 flex-1 border-0 bg-transparent px-0 text-xs shadow-none focus-visible:ring-0"
            aria-label="Адрес страницы"
            placeholder="Адрес сайта"
          />
        </div>
        <Button :disabled="busy || !allowed" size="sm" type="submit">{{
          busy ? "Загрузка…" : "Перейти"
        }}</Button>
        <Popover v-model:open="menuOpen">
          <PopoverTrigger as-child>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              class="size-8 shrink-0"
              aria-label="Меню браузера"
              :disabled="busy"
            >
              <MoreHorizontal class="size-4" />
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" class="w-80 space-y-1 p-2">
            <Button
              type="button"
              variant="ghost"
              class="h-auto w-full justify-start whitespace-normal text-left"
              :disabled="!allowed || !canReopen"
              @click="browserMenu('restore')"
            >
              <RotateCcw class="size-4 shrink-0" />
              <span
                >Восстановить закрытую вкладку<span class="block text-xs text-muted-foreground"
                  >Ctrl+Shift+T</span
                ></span
              >
            </Button>
            <Button
              type="button"
              variant="ghost"
              class="w-full justify-start"
              :disabled="!allowed"
              @click="browserMenu('settings')"
            >
              <Settings class="size-4" />Настройки браузера
            </Button>
            <Button
              type="button"
              variant="ghost"
              class="w-full justify-start"
              :disabled="!allowed"
              @click="browserMenu('extensions')"
            >
              <Puzzle class="size-4" />Расширения
            </Button>
            <fieldset class="space-y-3 border-t px-2 pt-3">
              <legend class="flex items-center gap-2 pt-2 text-xs font-medium">
                <Monitor class="size-3.5" />Отображение страницы
              </legend>
              <div class="flex items-end gap-2">
                <label class="min-w-0 flex-1 text-xs" :for="`${formId}-width`"
                  >Ширина, px
                  <Input
                    :id="`${formId}-width`"
                    v-model.number="width"
                    type="number"
                    min="320"
                    max="7680"
                    class="mt-1 h-8"
                  />
                </label>
                <label class="min-w-0 flex-1 text-xs" :for="`${formId}-height`"
                  >Высота, px
                  <Input
                    :id="`${formId}-height`"
                    v-model.number="height"
                    type="number"
                    min="240"
                    max="4320"
                    class="mt-1 h-8"
                  />
                </label>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                class="w-full"
                :disabled="busy || !allowed || !tabId"
                @click="resize"
                >Применить размер</Button
              >
              <label
                :for="`${formId}-zoom`"
                class="flex items-center justify-between gap-2 text-xs"
              >
                Масштаб просмотра
                <Select
                  :model-value="String(zoom)"
                  @update:model-value="(value) => (zoom = Number(value))"
                >
                  <SelectTrigger
                    :id="`${formId}-zoom`"
                    class="h-8 w-24"
                    aria-label="Масштаб просмотра"
                    ><SelectValue /></SelectTrigger
                  >
                  <SelectContent>
                    <SelectItem
                      v-for="value in [50, 75, 100, 125, 150, 200]"
                      :key="value"
                      :value="String(value)"
                      >{{ value }}%</SelectItem
                    >
                  </SelectContent>
                </Select>
              </label>
            </fieldset>
          </PopoverContent>
        </Popover>
      </form>

      <p v-if="notice" role="status" class="border-b px-3 py-2 text-sm">{{ notice }}</p>
      <div
        :id="`${formId}-page`"
        role="tabpanel"
        :aria-labelledby="tabId ? `${formId}-tab-${tabId}` : undefined"
      >
        <ProjectBrowserSurface
          v-if="preview"
          :preview="preview"
          :zoom="zoom"
          :height="height"
          :busy="busy"
          :allowed="allowed"
          @inputs="queueBrowserInputs"
          @notice="notice = $event"
        />
        <div
          v-else
          class="grid min-h-80 place-items-center px-6 py-12 text-center text-sm text-muted-foreground"
        >
          {{
            busy
              ? "Подготавливаем браузер…"
              : tabs.length
                ? "Выберите вкладку."
                : "Откройте сайт в адресной строке."
          }}
        </div>
        <details v-if="snapshot" :open="!preview" class="border-t px-3 py-2">
          <summary class="cursor-pointer text-xs text-muted-foreground">
            Текст страницы и элементы
          </summary>
          <div class="space-y-3 py-3">
            <h3 class="font-medium">{{ snapshot.title }}</h3>
            <pre class="whitespace-pre-wrap break-words font-sans text-sm">{{ snapshot.text }}</pre>
            <p v-if="snapshot.text_truncated" class="text-xs text-muted-foreground">
              Содержимое сокращено браузером.
            </p>
            <div v-if="elements.length" class="space-y-2 border-t pt-3">
              <div
                v-for="element in elements"
                :key="element.ref"
                class="flex flex-wrap items-center gap-2"
              >
                <label
                  class="min-w-0 flex-1 break-words text-sm"
                  :for="`${formId}-element-${element.ref}`"
                >
                  {{ element.name || element.text || element.role || element.tag || element.ref }}
                  <Input
                    v-if="editableBrowserElement(element)"
                    :id="`${formId}-element-${element.ref}`"
                    v-model="inputValues[element.ref]"
                    :type="element.type === 'password' ? 'password' : 'text'"
                    :disabled="busy || element.disabled"
                  />
                </label>
                <Button
                  variant="outline"
                  :disabled="
                    busy ||
                    element.disabled ||
                    element.type === 'file' ||
                    (editableBrowserElement(element) &&
                      inputValues[element.ref] === (element.value ?? ''))
                  "
                  @click="interact(element)"
                  >{{
                    editableBrowserElement(element) ? "Ввести" : "Нажать"
                  }}</Button
                >
              </div>
            </div>
          </div>
        </details>
      </div>
    </div>
  </section>
</template>
