<script setup lang="ts">
import {computed,ref,onBeforeUnmount} from "vue"
import {useI18n} from "vue-i18n"
import {Button} from "@/shared/ui/button"
import {Input} from "@/shared/ui/input"
import {CONTROL_PANEL_AUTH_API} from "@/shared/config/control-panel-api"
import {readBoundedJsonResponse} from "@/shared/lib/bounded-json-response"
import {solveRauthyPow} from "../model/rauthy-pow"
const props=defineProps<{mode:"invitation"|"recovery"}>()
const emit=defineEmits<{back:[]}>()
const {locale}=useI18n()
const link=ref(""),password=ref(""),confirmation=ref(""),email=ref("")
const prepared=ref(false),busy=ref(false),done=ref(false),notice=ref("")
const policy=ref<Record<string,number>>({})
const passwordRules=computed(()=>[
  `Длина: ${policy.value.length_min??1}–${policy.value.length_max??256} символов.`,
  ...Object.entries({include_lower_case:'строчных букв',include_upper_case:'заглавных букв',include_digits:'цифр',include_special:'специальных символов'})
    .filter(([key])=>(policy.value[key]??0)>0).map(([key,label])=>`Не менее ${policy.value[key]} ${label}.`),
].join(' '))
let controller:AbortController|null=null
async function call(path:string,data:Record<string,unknown>,signal:AbortSignal){
  const response=await fetch(CONTROL_PANEL_AUTH_API+"/password-setup/"+path,{
    method:"POST",credentials:"same-origin",mode:"same-origin",redirect:"error",cache:"no-store",referrerPolicy:"no-referrer",signal,
    headers:{Accept:"application/json","Content-Type":"application/json"},body:JSON.stringify(data),
  })
  const result=await readBoundedJsonResponse(response,signal,8192) as Record<string,any>
  if(!response.ok)throw new Error(result.error?.code||"SETUP_PROVIDER_UNAVAILABLE")
  return result
}
async function run(action:"prepare"|"finish"|"recovery"){
  if(busy.value)return
  busy.value=true;notice.value=""
  const request=new AbortController();controller=request
  const timer=setTimeout(()=>request.abort(),65000)
  try{
    if(action==="prepare"){
      const value=link.value.trim()
      const match=value.match(/^(?:https?:\/\/[^/]+)?\/auth\/v1\/users\/([A-Za-z0-9]{24})\/reset\/([A-Za-z0-9]{64})(?:\?type=[^#]*)?$/)||value.match(/^([A-Za-z0-9]{24}):([A-Za-z0-9]{64})$/)
      if(!match)throw new Error("SETUP_CODE_INVALID_OR_EXPIRED")
      const result=await call("prepare",{user_id:match[1],code:match[2]},request.signal)
      policy.value=result.password_policy
      prepared.value=true
    }else if(action==="finish"){
      await call("finish",{password:password.value},request.signal)
      password.value="";confirmation.value="";link.value="";done.value=true
    }else{
      const challenge=await call("recovery-pow",{},request.signal)
      const solution=await solveRauthyPow(challenge.challenge,request.signal)
      if(solution.kind!=="solved")throw new Error("SETUP_PROVIDER_UNAVAILABLE")
      await call("recovery-request",{email:email.value,pow:solution.work},request.signal)
      notice.value=locale.value==='ru'?"Запрос принят. Если учётная запись существует, провайдер обработает восстановление. Доставка письма не подтверждена.":"Request accepted. The provider processes recovery if the account exists. Email delivery is unconfirmed."
    }
  }catch(error){
    const code=error instanceof Error?error.message:""
    const messages:Record<string,string>={
      RAUTHY_INVITATION_MAIL_UNCONFIGURED:"Отправка почты не настроена. Администратору необходимо настроить SMTP Rauthy.",
      SETUP_CODE_INVALID_OR_EXPIRED:"Ссылка или код недействительны, истекли либо уже привязаны к другому сеансу.",
      SETUP_PROVIDER_REJECTED:"Провайдер отклонил пароль или требует MFA. Проверьте правила пароля и подготовьте ссылку заново.",
      SETUP_OUTCOME_UNCONFIRMED:"Результат не подтверждён. Сначала попробуйте войти с новым паролем.",
    }
    notice.value=locale.value==='ru'?(messages[code]||"Провайдер недоступен. Повторите попытку после восстановления связи."):(code||"Provider unavailable")
    if(action==="finish")prepared.value=false
  }finally{clearTimeout(timer);busy.value=false;controller=null}
}
onBeforeUnmount(()=>{controller?.abort();password.value="";confirmation.value="";link.value=""})
</script>
<template>
  <section class="space-y-5 rounded-2xl border border-border bg-card p-7">
    <h1 class="text-xl font-semibold">{{mode==='invitation'?'Регистрация по приглашению':'Восстановление доступа'}}</h1>
    <p v-if="done" role="status" class="text-sm">Пароль принят провайдером. Теперь войдите с email и новым паролем.</p>
    <template v-else>
      <form v-if="mode==='recovery'&&!prepared" class="space-y-3" @submit.prevent="run('recovery')">
        <label class="block text-sm">Электронная почта<Input v-model="email" type="email" autocomplete="email" required :disabled="busy"/></label>
        <Button :disabled="busy||!email" class="w-full">Запросить восстановление</Button>
      </form>
      <form v-if="!prepared" class="space-y-3" @submit.prevent="run('prepare')">
        <p class="text-sm text-muted-foreground">Скопируйте ссылку из письма, не открывая её, или вставьте код в формате ID:код. Установка пароля проходит здесь.</p>
        <label class="block text-sm">Ссылка или код из письма<Input v-model="link" autocomplete="off" required :disabled="busy" maxlength="1024"/></label>
        <Button variant="outline" :disabled="busy||!link" class="w-full">Продолжить</Button>
      </form>
      <form v-else class="space-y-3" @submit.prevent="run('finish')">
        <p class="text-sm text-muted-foreground">{{passwordRules}}</p>
        <label class="block text-sm">Новый пароль<Input v-model="password" type="password" autocomplete="new-password" required maxlength="256" :disabled="busy"/></label>
        <label class="block text-sm">Повторите пароль<Input v-model="confirmation" type="password" autocomplete="new-password" required maxlength="256" :disabled="busy"/></label>
        <Button :disabled="busy||!password||password!==confirmation" class="w-full">Сохранить пароль</Button>
      </form>
    </template>
    <p v-if="notice" role="status" class="text-sm text-muted-foreground">{{notice}}</p>
    <Button variant="ghost" :disabled="busy" @click="emit('back')">Вернуться ко входу</Button>
  </section>
</template>
