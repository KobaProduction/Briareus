import {ref,onMounted,onBeforeUnmount} from "vue"
import {PlatformCommandFailure} from "./administration-contracts"
import type {InvitationPort,InvitationCapabilities,InvitationCommand} from "./invitation-contracts"
export function useInvitations(port:InvitationPort,onChanged:()=>void){
const capabilities=ref<InvitationCapabilities|null>(null),email=ref(""),busy=ref(false),notice=ref("")
const pending=ref<InvitationCommand|null>(null)
const request=new AbortController()
let capabilityRevision=0
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
  const revision=++capabilityRevision
  try{
    const result=await port.capabilities(request.signal)
    if(!request.signal.aborted&&revision===capabilityRevision)capabilities.value=result
  }catch{if(!request.signal.aborted&&revision===capabilityRevision){capabilities.value=null;notice.value="Не удалось проверить право приглашать пользователей."}}
}
async function complete(command:InvitationCommand):Promise<void>{
  if(request.signal.aborted)return
  notice.value=command.action==='invitation.issue'?"Учётная запись создана в Rauthy, запрос на письмо принят провайдером. Доставка не подтверждена. Приглашение не добавляет пользователя в команды и не выдаёт административные права.":"Право inviter обновлено."
  pending.value=null;email.value="";await load()
  if(!request.signal.aborted)onChanged()
}
async function failed(error:unknown):Promise<void>{
  if(request.signal.aborted)return
  const code=error instanceof PlatformCommandFailure?error.code:"UNAVAILABLE"
  notice.value=messages[code]||"Сервер не подтвердил результат операции."
  if(error instanceof PlatformCommandFailure&&!error.uncertain){pending.value=null;await load()}
}
async function send(command?:InvitationCommand){
  if(busy.value||request.signal.aborted)return
  if(command&&!pending.value)pending.value=command
  if(!pending.value)return
  busy.value=true;notice.value=""
  try{
    const command=pending.value
    await port.command(command,request.signal)
    await complete(command)
  }catch(error){
    await failed(error)
  }finally{busy.value=false}
}
const stop=port.onChange(()=>{void load()})
onMounted(()=>{void load()})
onBeforeUnmount(()=>{stop();request.abort()})

function issue():Promise<void> {
 if(!capabilities.value?.can_invite)return Promise.resolve();
 return send({operation_uuid:crypto.randomUUID(),action:"invitation.issue",data:{email:email.value.trim()}});
}
function toggleInviter(userId:string):Promise<void> {
 const current=capabilities.value;
 if(!current?.can_manage_inviters)return Promise.resolve();
 return send({operation_uuid:crypto.randomUUID(),action:"inviter.set",data:{user_id:userId,enabled:!current.inviter_ids.includes(userId)}});
}
return {capabilities,email,busy,notice,pending,messages,issue,toggleInviter,retry:()=>send()};
}
