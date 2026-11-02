import {onBeforeUnmount,ref} from "vue"
import {readRauthyPanelState,type RauthyPanelState} from "@/entities/identity"
import {submitNativePasswordLogin,type NativeLoginOutcome} from "../api/native-first-factor"
import {cancelNativePrelogin} from "../api/native-prelogin-control"
import {nativeOtp} from "../api/native-otp"

type LoginViewState=RauthyPanelState|{kind:"checking"}
type LoginMessage="invalid"|"provider"|"mfa"|"rate_limited"|"expired"|"unavailable"|"unconfirmed"|"cancelled"
interface NativeSignInOptions{
  sessionBusy:()=>boolean
  sessionState:()=>LoginViewState
  acceptState:(state:LoginViewState)=>void
}
function loginFailureMessage(kind:NativeLoginOutcome["kind"]):LoginMessage{
  switch(kind){
    case "continuation_unavailable":return "mfa"
    case "rate_limited":return "rate_limited"
    case "expired":return "expired"
    case "provider_rejected":return "provider"
    case "rejected":return "invalid"
    case "cancelled":return "cancelled"
    default:return "unavailable"
  }
}
/** Component-scoped, one-attempt workflow. Provider success is reconciled with
 * the signed session endpoint before the presentation accepts any identity. */
export function useNativeSignIn(options:NativeSignInOptions){
const email=ref("")
const password=ref("")
const passwordVisible=ref(false)
const loginBusy=ref(false)
const cancellingLogin=ref(false)
const otpMethods=ref<number[]>([]),otpSent=ref(false),otpCode=ref("")
const loginMessage=ref<"invalid"|"provider"|"mfa"|"rate_limited"|"expired"|"unavailable"|"unconfirmed"|"cancelled"|null>(null)
let loginController:AbortController|null=null
async function submitLogin():Promise<void>{
  if(loginBusy.value||options.sessionBusy()||options.sessionState().kind!=="signed_out")return
  const userEmail=email.value
  const userPassword=password.value
  // Preserve the input on a rejected/unavailable attempt: the user may
  // correct a typo or retry without retyping an otherwise valid password.
  // It stays only in this component's memory, never in storage or logs.
  loginMessage.value=null
  const request=new AbortController()
  loginController?.abort()
  loginController=request
  loginBusy.value=true
  const deadline=setTimeout(()=>request.abort(),65000)
  try{
    const outcome:NativeLoginOutcome=await submitNativePasswordLogin(userEmail,userPassword,request.signal)
    if(loginController!==request)return
    await acceptLoginOutcome(outcome,request)
  }catch{
    if(loginController===request)loginMessage.value="unconfirmed"
  }finally{
    clearTimeout(deadline)
    if(loginController===request){loginController=null;loginBusy.value=false}
  }
}
async function continueOtp(method?:number):Promise<void>{
  if(loginBusy.value)return
  loginBusy.value=true;loginMessage.value=null
  const request=new AbortController();loginController=request
  const timer=setTimeout(()=>request.abort(),35000)
  try{
    if(!await sendOtp(method,request.signal))throw new Error()
    if(loginController!==request)return
    await acceptOtpResult(method,request)
  }catch{if(loginController===request){otpMethods.value=[];otpSent.value=false;otpCode.value="";loginMessage.value="expired"}}
  finally{clearTimeout(timer);if(loginController===request){loginBusy.value=false;loginController=null}}
}
async function acceptLoginOutcome(outcome:NativeLoginOutcome,request:AbortController):Promise<void>{
  if(outcome.kind==="otp_pending"){
    clearPassword();otpMethods.value=outcome.methods;otpSent.value=false
    return
  }
  if(outcome.kind==="session_issued"||outcome.kind==="uncertain"){
    await verifyLoginResult(request)
    return
  }
  if(outcome.kind==="continuation_unavailable")clearPassword()
  loginMessage.value=loginFailureMessage(outcome.kind)
}
async function acceptOtpResult(method:number|undefined,request:AbortController):Promise<void>{
  if(method!==undefined){otpSent.value=true;return}
  const result=await readRauthyPanelState(request.signal)
  if(loginController!==request)return
  if(request.signal.aborted||result.kind!=="signed_in")throw new Error()
  otpMethods.value=[];otpCode.value="";options.acceptState(result)
}
async function cancelLogin():Promise<void>{
  if(!loginBusy.value||cancellingLogin.value)return
  cancellingLogin.value=true
  loginController?.abort()
  loginController=null
  password.value=""
  passwordVisible.value=false
  const request=new AbortController()
  const deadline=setTimeout(()=>request.abort(),8000)
  try{
    // Keep the form locked until Backend confirms cancellation; otherwise a
    // late cancel could revoke a new cookie-bound attempt.
    const result=await cancelNativePrelogin(request.signal)
    loginMessage.value=result.kind==="cancelled"?"cancelled":"unconfirmed"
  }finally{
    clearTimeout(deadline)
    loginBusy.value=false
    cancellingLogin.value=false
  }
}
async function verifyLoginResult(request:AbortController):Promise<void>{
  const read=await readRauthyPanelState(request.signal)
  if(loginController!==request)return
  if(!request.signal.aborted&&read.kind==="signed_in"){
    options.acceptState(read)
    loginMessage.value=null
  }else loginMessage.value="unconfirmed"
}
function sendOtp(method:number|undefined,signal:AbortSignal):Promise<boolean>{
  return method===undefined?nativeOtp("finish",otpCode.value,signal):nativeOtp("start",method,signal)
}
function clearPassword():void{password.value="";passwordVisible.value=false}
function invalidateLogin():void{
  loginController?.abort();loginController=null
  // An in-flight server cancellation still owns the attempt cookie until its
  // reply: a parent snapshot must not enable a replacement password attempt.
  loginBusy.value=cancellingLogin.value
  otpMethods.value=[];otpSent.value=false;otpCode.value=""
  clearPassword()
}
onBeforeUnmount(invalidateLogin)
return {email,password,passwordVisible,loginBusy,cancellingLogin,otpMethods,otpSent,otpCode,loginMessage,submitLogin,continueOtp,cancelLogin,clearPassword,invalidateLogin}
}
