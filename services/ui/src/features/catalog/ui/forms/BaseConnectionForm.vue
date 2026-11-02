<script setup lang="ts">
import {Textarea} from "@/shared/ui/textarea"
import { useId } from "vue"
import {CheckCircle2,Loader2,PlugZap} from "lucide-vue-next"
import {Button} from "@/shared/ui/button"
import {Input} from "@/shared/ui/input"
import {Dialog,DialogContent,DialogDescription,DialogHeader,DialogTitle} from "@/shared/ui/dialog"
import {connectionProviders,type ConnectionDraft,type ConnectionProvider} from "../../model/connection-draft"
import type { ConnectionSubmit } from "../../model/connection-contracts"
import { useConnectionEditor } from "../../model/use-connection-editor"
import GitPolicyFields from './GitPolicyFields.vue'
import GitHubConnectionFields from "./GitHubConnectionFields.vue"
import GitLabConnectionFields from "./GitLabConnectionFields.vue"
import InfrastructureConnectionFields from "./InfrastructureConnectionFields.vue"

const props=defineProps<{provider:ConnectionProvider;busy:boolean;message:string;initial?:Partial<ConnectionDraft>;
  submit:ConnectionSubmit}>()
const emit=defineEmits<{close:[];saved:[]}>()
const fieldId = useId()
const { draft, verified, discard, valid, verify, save, close } = useConnectionEditor({
  provider: props.provider, initial: props.initial, busy: () => props.busy,
  submit: (...args) => props.submit(...args), saved: () => emit("saved"), close: () => emit("close"),
})
</script>
<template>
  <Dialog :open="true" @update:open="value=>{if(!value)close()}">
    <DialogContent class="max-h-[90vh] overflow-y-auto sm:max-w-xl" @interact-outside.prevent>
      <DialogHeader><DialogTitle>{{initial?'Изменить аккаунт':'Подключить'}} {{connectionProviders[provider].title}}</DialogTitle>
        <DialogDescription>{{connectionProviders[provider].description}}. Данные подключения сохраняются для выбранного проекта.</DialogDescription></DialogHeader>
      <form class="space-y-5" @submit.prevent="save">
        <label :for="`${fieldId}-name`" class="block space-y-2 text-sm font-medium">Название подключения
          <Input :id="`${fieldId}-name`" v-model="draft.name" required maxlength="128" :disabled="busy" placeholder="Например, команда разработки"/>
        </label>
        <GitHubConnectionFields v-if="provider==='github'" v-model="draft" :disabled="busy" :editing="!!initial"/>
        <GitLabConnectionFields v-else-if="provider==='gitlab'" v-model="draft" :disabled="busy" :editing="!!initial"/>
        <InfrastructureConnectionFields v-else v-model="draft" :disabled="busy" :editing="!!initial"/>
        <GitPolicyFields v-if="draft.git_policy" v-model="draft.git_policy" :provider="provider" :disabled="busy"/>
        <details v-if="provider!=='github'" class="rounded-lg border px-3 py-2 text-sm">
          <summary class="cursor-pointer text-muted-foreground">Собственный центр сертификации</summary>
          <label :for="`${fieldId}-certificate`" class="mt-3 block space-y-2 text-xs">Сертификат CA · PEM
            <Textarea :id="`${fieldId}-certificate`" v-model="draft.ca_cert_pem" :disabled="busy" spellcheck="false" maxlength="16384" class="min-h-24 w-full rounded-md border bg-background p-2 font-mono text-xs" placeholder="-----BEGIN CERTIFICATE-----"/>
          </label>
        </details>
        <div v-if="message||verified" role="status" class="rounded-lg border p-3 text-sm" :class="verified?'border-emerald-500/30 bg-emerald-500/5':''">
          <span v-if="verified" class="flex items-center gap-2"><CheckCircle2 class="size-4"/>Подключение подтверждено</span><span v-else>{{message}}</span>
        </div>
        <p class="text-xs leading-5 text-muted-foreground">Ключ передаётся в зашифрованное хранилище Resources. Сохранённый ключ нельзя просмотреть в панели.</p>
        <div v-if="discard" class="space-y-3 rounded-lg border bg-muted/30 p-3 text-sm">Закрыть форму и удалить введённые данные?
          <div class="mt-2 flex gap-2"><Button type="button" variant="destructive" @click="emit('close')">Удалить черновик</Button><Button type="button" variant="outline" @click="discard=false">Продолжить</Button></div>
        </div>
        <div class="flex flex-wrap justify-end gap-2 border-t pt-4">
          <Button type="button" variant="ghost" :disabled="busy" @click="close">Отмена</Button>
          <Button type="button" variant="outline" :disabled="busy||!valid" @click="verify"><Loader2 v-if="busy" class="mr-2 size-4 animate-spin"/><PlugZap v-else class="mr-2 size-4"/>Проверить</Button>
          <Button type="submit" :disabled="busy||!valid||!verified">{{initial?'Сохранить изменения':'Добавить подключение'}}</Button>
        </div>
      </form>
    </DialogContent>
  </Dialog>
</template>
