<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { setLocale } from "@/shared/i18n"
import { uiPreferences } from "@/shared/lib/preferences"
import { browserTelemetry } from "@/features/platform/model/browser-telemetry"
import PageHeader from "@/shared/ui/PageHeader.vue"
import { Button } from "@/shared/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/card"
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from "@/shared/ui/select"
import { Switch } from "@/shared/ui/switch"

const {t}=useI18n()
function localeChanged(value:unknown):void {
  if(value==="en"||value==="ru")setLocale(value)
}

function densityChanged(value:unknown):void {
  if(value==="compact"||value==="comfortable")uiPreferences.density.value=value
}
function zoneChanged(value:unknown):void {
  if(value==="UTC"||value==="system")uiPreferences.displayTimeZone.value=value
}
</script>
<template>
  <div class="grid items-start gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(18rem,2fr)]">
    <PageHeader class="xl:col-span-2" :title="t('platform.navigation.settings')" :description="t('settings.interface')" />
    <Card>
      <CardHeader><CardTitle class="text-base">{{t('settings.interface')}}</CardTitle></CardHeader>
      <CardContent class="space-y-5">
        <div class="space-y-2 text-sm">
          <p class="font-semibold">{{t('settings.language')}}</p>
          <Select :model-value="uiPreferences.locale.value" @update:model-value="localeChanged">
            <SelectTrigger class="min-h-10" :aria-label="t('settings.language')"><SelectValue/></SelectTrigger>
            <SelectContent>
              <SelectItem value="ru">Русский</SelectItem>
              <SelectItem value="en">English</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div class="space-y-2 text-sm">
          <p class="font-semibold">{{t('settings.density')}}</p>
          <Select :model-value="uiPreferences.density.value" @update:model-value="densityChanged">
            <SelectTrigger class="min-h-10" :aria-label="t('settings.density')"><SelectValue/></SelectTrigger>
            <SelectContent>
              <SelectItem value="compact">{{t('common.compact')}}</SelectItem>
              <SelectItem value="comfortable">{{t('common.comfortable')}}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div class="space-y-2 text-sm">
          <p class="font-semibold">{{t('platform.displayTimeZone')}}</p>
          <Select :model-value="uiPreferences.displayTimeZone.value" @update:model-value="zoneChanged">
            <SelectTrigger class="min-h-10" :aria-label="t('platform.displayTimeZone')"><SelectValue/></SelectTrigger>
            <SelectContent>
              <SelectItem value="system">{{t('platform.deviceTimeZone')}}</SelectItem>
              <SelectItem value="UTC">UTC</SelectItem>
            </SelectContent>
          </Select>
          <p class="text-xs leading-5 text-muted-foreground">{{t('platform.displayTimeZoneHint')}}</p>
        </div>
        <div class="space-y-2 text-sm"><p class="font-semibold">Частота обновления времени</p><Select :model-value="String(uiPreferences.timeUpdateIntervalMs.value)" @update:model-value="value=>{const interval=Number(value);if([1000,5000,15000,60000].includes(interval))uiPreferences.timeUpdateIntervalMs.value=interval}"><SelectTrigger aria-label="Частота обновления относительного времени"><SelectValue/></SelectTrigger><SelectContent><SelectItem v-for="seconds in [1,5,15,60]" :key="seconds" :value="String(seconds*1000)">{{seconds}} с</SelectItem></SelectContent></Select><p class="text-xs text-muted-foreground">Единый таймер для всех видимых отметок времени. Больший интервал снижает частоту перерисовок. На события сервера и срок полномочий не влияет.</p></div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader><CardTitle class="text-base">{{t('platform.browserDiagnostics')}}</CardTitle></CardHeader>
      <CardContent class="space-y-4">
        <div class="flex items-center gap-3">
          <Switch :model-value="uiPreferences.diagnosticsConsent.value"
            :aria-label="t('platform.browserDiagnosticsConsent')"
            @update:model-value="enabled=>uiPreferences.diagnosticsConsent.value=enabled"/>
          <span class="text-sm">{{t('platform.browserDiagnosticsConsent')}}</span>
        </div>
        <p class="text-xs leading-5 text-muted-foreground">{{t('platform.browserDiagnosticsPrivacy')}}</p>
        <p role="status" class="text-xs text-muted-foreground">
          {{t('platform.browserDiagnosticsCount',{count:browserTelemetry.state.buffered})}}
          · {{t('platform.browserDiagnosticsNoRelay')}}
        </p>
        <Button variant="outline" size="sm" @click="browserTelemetry.clear()">{{t('platform.clearDiagnostics')}}</Button>
      </CardContent>
    </Card>
  </div>
</template>
