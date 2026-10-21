<script setup lang="ts">
import {Textarea} from "@/shared/ui/textarea"
import {computed,onBeforeUnmount,ref,watch} from "vue"
import {CheckCircle2,Loader2,PlugZap} from "lucide-vue-next"
import {Button} from "@/shared/ui/button"
import {Input} from "@/shared/ui/input"
import {Dialog,DialogContent,DialogDescription,DialogHeader,DialogTitle} from "@/shared/ui/dialog"
import {connectionConfiguration,connectionDraftDirty,connectionProviders,newConnectionDraft,type ConnectionDraft,type ConnectionProvider} from "../../model/connection-draft"
import GitPolicyFields from './GitPolicyFields.vue'
import GitHubConnectionFields from "./GitHubConnectionFields.vue"
import GitLabConnectionFields from "./GitLabConnectionFields.vue"
import InfrastructureConnectionFields from "./InfrastructureConnectionFields.vue"

const props=defineProps<{provider:ConnectionProvider;busy:boolean;message:string;initial?:Partial<ConnectionDraft>;
  submit:(action:"verify"|"create",configuration:Record<string,unknown>,credential:string)=>Promise<Record<string,unknown>|null>}>()
const emit=defineEmits<{close:[];saved:[]}>()
const baseline={...newConnectionDraft(props.provider),...props.initial,credential:""}
const draft=ref<ConnectionDraft>(JSON.parse(JSON.stringify(baseline)))
let generation=0
const verifiedRevision=ref(-1),verified=ref(false),discard=ref(false)
const dirty=computed(()=>connectionDraftDirty(draft.value,baseline))
const valid=computed(()=>!!draft.value.name.trim()&&(!!draft.value.credential||!!props.initial)&&
  (draft.value.auth_type!=="github_app"||/^[1-9][0-9]*$/.test(draft.value.external_id)))
watch(draft,()=>{generation++;verified.value=false;verifiedRevision.value=-1},{deep:true,flush:"sync"})
watch(()=>draft.value.auth_type,()=>{draft.value.credential=""},{flush:"sync"})
async function verify(){
  const run=generation
  const result=await props.submit("verify",connectionConfiguration(draft.value),draft.value.credential)
  if(run===generation&&result?.status==="connected"){verifiedRevision.value=run;verified.value=true}
}
async function save(){
  if(!verified.value||verifiedRevision.value!==generation)return
  const result=await props.submit("create",connectionConfiguration(draft.value),draft.value.credential)
  if(result?.item){draft.value.credential="";emit("saved")}
}
function close(){if(props.busy)return;if(dirty.value)discard.value=true;else emit("close")}
onBeforeUnmount(()=>{draft.value.credential="";draft.value.ca_cert_pem=""})
</script>
<template>
  <Dialog :open="true" @update:open="value=>{if(!value)close()}">
    <DialogContent class="max-h-[90vh] overflow-y-auto sm:max-w-xl" @interact-outside.prevent>
      <DialogHeader><DialogTitle>{{initial?'Изменить аккаунт':'Подключить'}} {{connectionProviders[provider].title}}</DialogTitle>
        <DialogDescription>{{connectionProviders[provider].description}}. Данные подключения сохраняются для выбранного проекта.</DialogDescription></DialogHeader>
      <form class="space-y-5" @submit.prevent="save">
        <label class="block space-y-2 text-sm font-medium">Название подключения
          <Input v-model="draft.name" required maxlength="128" :disabled="busy" placeholder="Например, команда разработки"/>
        </label>
        <GitHubConnectionFields v-if="provider==='github'" v-model="draft" :disabled="busy" :editing="!!initial"/>
        <GitLabConnectionFields v-else-if="provider==='gitlab'" v-model="draft" :disabled="busy" :editing="!!initial"/>
        <InfrastructureConnectionFields v-else v-model="draft" :disabled="busy" :editing="!!initial"/>
        <GitPolicyFields v-if="draft.git_policy" v-model="draft.git_policy" :provider="provider" :disabled="busy"/>
        <details v-if="provider!=='github'" class="rounded-lg border px-3 py-2 text-sm">
          <summary class="cursor-pointer text-muted-foreground">Собственный центр сертификации</summary>
          <label class="mt-3 block space-y-2 text-xs">Сертификат CA · PEM
            <Textarea v-model="draft.ca_cert_pem" :disabled="busy" spellcheck="false" maxlength="16384" class="min-h-24 w-full rounded-md border bg-background p-2 font-mono text-xs" placeholder="-----BEGIN CERTIFICATE-----"/>
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
