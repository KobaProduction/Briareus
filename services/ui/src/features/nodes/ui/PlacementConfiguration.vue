<script setup lang="ts">
import {useId} from "vue"
const formId=useId()
import {computed} from 'vue'
import type {ModuleConfiguration} from '../model/module-configuration'
import {Input} from '@/shared/ui/input'
import {Switch} from '@/shared/ui/switch'
import {Select,SelectContent,SelectItem,SelectTrigger,SelectValue} from '@/shared/ui/select'
import {Badge} from '@/shared/ui/badge'
const props=defineProps<{module:string}>()
const model=defineModel<ModuleConfiguration>({required:true})
const mode=computed({get:()=>model.value.browser?.external_enabled?'external':'managed',set:(value:string)=>{
  if(model.value.browser)model.value={...model.value,browser:{...model.value.browser,external_enabled:value==='external'}}
}})
</script>
<template>
 <fieldset v-if="props.module==='web'&&model.browser" class="space-y-3 border-t pt-3">
  <legend class="text-sm font-medium">Браузер агента</legend>
  <label :for="`${formId}-mode`" class="block space-y-1 text-sm">Режим браузера<Select v-model="mode"><SelectTrigger :id="`${formId}-mode`"><SelectValue/></SelectTrigger><SelectContent><SelectItem value="managed">Chromium ноды</SelectItem><SelectItem value="external">Подключённый внешний браузер</SelectItem></SelectContent></Select></label>
  <p class="text-xs text-muted-foreground">Chromium работает внутри этой ноды. Внешний режим использует явно настроенный MCP-сервер браузера.</p>
  <label :for="`${formId}-url`" v-if="model.browser.external_enabled||model.browser.external_mcp_url" class="block space-y-1 text-sm">HTTPS-адрес MCP внешнего браузера<Input :id="`${formId}-url`" v-model="model.browser.external_mcp_url" type="url" maxlength="2048" placeholder="https://browser.example/mcp"/></label>
  <label :for="`${formId}-developer`" class="flex items-center justify-between gap-3 text-sm"><span>Инструменты разработчика для агента</span><Switch :id="`${formId}-developer`" v-model="model.browser.developer_access_enabled"/></label>
  <p class="text-xs text-muted-foreground">Доступ к инструментам по-прежнему требует разрешений текущего агентского сеанса.</p>
 </fieldset>
 <fieldset v-else-if="props.module==='serena'&&model.serena" class="space-y-3 border-t pt-3">
  <legend class="text-sm font-medium">Serena · программирование</legend>
  <label :for="`${formId}-path`" class="block space-y-1 text-sm">Каталог проекта<Input :id="`${formId}-path`" v-model="model.serena.project_path" maxlength="512" placeholder=". или repositories/project"/></label>
  <p class="text-xs text-muted-foreground">Путь относительно рабочей папки проекта на ноде, общей с Terminal и Git. Модуль Files необязателен. Точка означает корень; выход за пределы папки запрещён.</p>
  <div class="flex items-center gap-2 text-sm"><span>Семантический анализ</span><Badge variant="outline">LSP</Badge></div>
 </fieldset>
</template>
