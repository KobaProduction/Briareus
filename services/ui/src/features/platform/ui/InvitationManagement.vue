<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount} from "vue"
import {eventBus} from "@/shared/events/bus"
import {RpcError} from "@/shared/events/protocol"
import {Button} from "@/shared/ui/button"
import {Input} from "@/shared/ui/input"
import {Card,CardHeader,CardTitle,CardContent} from "@/shared/ui/card"
const props=defineProps<{users?:{id:string;name:string|null;email:string|null}[]}>()
const emit=defineEmits<{changed:[]}>()
interface Capabilities {can_invite:boolean;can_manage_inviters:boolean;inviter_ids:string[];unavailable_reason:string|null}
const capabilities=ref<Capabilities|null>(null),email=ref(""),busy=ref(false),notice=ref("")
const pending=ref<{operation_uuid:string;action:string;data:Record<string,unknown>}|null>(null)
const request=new AbortController()
const messages:Record<string,string>={
  RAUTHY_INVITATION_MAIL_UNCONFIGURED:"Почта Rauthy не настроена. Отправка приглашений недоступна до настройки SMTP.",
  RAUTHY_INVITATION_KEY_UNAVAILABLE:"Не настроен отдельный служебный ключ Rauthy Users:create для приглашений.",
  RAUTHY_ACCOUNT_ALREADY_EXISTS:"Учётная запись уже существует. Пользователь может войти с ней — доступ создастся автоматически.",
  INVITER_REQUIRED:"Нет права приглашать пользователей.",PLATFORM_OPERATOR_REQUIRED:"Назначать inviter может только оператор.",
  INVITATION_ALREADY_REQUESTED:"Для этого адреса уже зарегистрировано приглашение.",
  INVITATION_OUTCOME_UNCONFIRMED:"Результат запроса неизвестен. Повторная отправка письма заблокирована; оператор должен проверить создание учётной записи.",
  EMAIL_INVALID:"Проверьте адрес электронной почты.",
}
async function load(){
  try{
    const result=await eventBus.request<Capabilities>('platform.command',{operation_uuid:crypto.randomUUID(),action:'invitation.capabilities',data:{}},request.signal)
    if(typeof result.can_invite!=="boolean"||typeof result.can_manage_inviters!=="boolean"||!Array.isArray(result.inviter_ids))throw new Error()
    capabilities.value=result
  }catch{capabilities.value=null;notice.value="Не удалось проверить право приглашать пользователей."}
}
async function send(action?:string,data?:Record<string,unknown>){
  if(busy.value)return
  if(action&&!pending.value)pending.value={operation_uuid:crypto.randomUUID(),action,data:data??{}}
  if(!pending.value)return
  busy.value=true;notice.value=""
  try{
    const command=pending.value
    const result=await eventBus.request<{delivery?:string}>('platform.command',command,request.signal)
    notice.value=command.action==='invitation.issue'?"Учётная запись создана в Rauthy, запрос на письмо принят провайдером. Доставка не подтверждена. Приглашение не добавляет пользователя в команды и не выдаёт административные права.":"Право inviter обновлено."
    void result
    pending.value=null;email.value="";await load();emit('changed')
  }catch(error){
    const code=error instanceof RpcError?error.message:"UNAVAILABLE"
    notice.value=messages[code]||"Сервер не подтвердил результат операции."
    if(error instanceof RpcError&&!error.uncertain){pending.value=null;await load()}
  }finally{busy.value=false}
}
const stop=eventBus.subscribe('management.events',()=>{void load()})
onMounted(()=>{void load()})
onBeforeUnmount(()=>{stop();request.abort()})
</script>
<template>
  <Card v-if="capabilities?.can_invite||notice">
    <CardHeader><CardTitle>Приглашения в систему</CardTitle></CardHeader>
    <CardContent class="space-y-4">
      <p v-if="capabilities?.unavailable_reason" role="status" class="text-sm text-muted-foreground">{{messages[capabilities.unavailable_reason]||'Приглашения пока недоступны.'}}</p>
      <form v-if="capabilities?.can_invite" class="flex flex-wrap gap-3" @submit.prevent="send('invitation.issue',{email:email.trim()})">
        <label class="min-w-56 flex-1 text-sm">Электронная почта<Input v-model="email" type="email" autocomplete="email" required maxlength="254" :disabled="busy||!!pending"/></label>
        <Button class="self-end" :disabled="busy||!!pending||!email||!!capabilities.unavailable_reason">Пригласить</Button>
      </form>
      <div v-if="capabilities?.can_manage_inviters&&props.users" class="space-y-2">
        <p class="text-sm text-muted-foreground">Кто может приглашать пользователей. Операторы уже имеют это право.</p>
        <div v-for="user in props.users" :key="user.id" class="flex items-center justify-between gap-3 border-b py-2 text-sm">
          <span>{{user.name||user.email||'Пользователь'}}</span>
          <Button variant="outline" size="sm" :disabled="busy||!!pending" @click="send('inviter.set',{user_id:user.id,enabled:!capabilities!.inviter_ids.includes(user.id)})">{{capabilities.inviter_ids.includes(user.id)?'Отозвать inviter':'Разрешить приглашать'}}</Button>
        </div>
      </div>
      <p v-if="notice" role="status" class="text-sm">{{notice}}</p>
      <Button v-if="pending" variant="outline" :disabled="busy" @click="send()">Проверить исходную операцию</Button>
    </CardContent>
  </Card>
</template>
