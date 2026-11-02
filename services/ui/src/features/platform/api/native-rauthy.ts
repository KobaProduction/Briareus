import {readBoundedJsonResponse,readBoundedErrorCode} from "@/shared/lib/transport"
import {CONTROL_PANEL_AUTH_API} from "@/shared/config"
import {nativeInitLifetime} from "../model/native-auth-protocol"
/** Backend native Rauthy transaction Init, not login or authorization.
 * The one-use PoW endpoint is intentionally NOT called here: there is no
 * credential/MFA submit API yet, and consuming its challenge would burn the
 * transaction's only PoW reservation before the first factor can use it.
 * Private provider cookies, CSRF and PKCE state stay server-side.
 */
export type NativePreparation =
  | {kind:"prepared";expiresIn:number;expiresAt:number}
  | {kind:"unavailable"|"forbidden"|"invalid"|"expired";code:string}

const REQUEST:RequestInit={
  method:"POST",credentials:"same-origin",mode:"same-origin",
  cache:"no-store",redirect:"error",referrerPolicy:"no-referrer",
  headers:{Accept:"application/json","Content-Type":"application/json"},
  body:"{}",
}

/** Explicitly user-triggered same-origin, credential-free Init only.
 * Caller restricts invocation to a secure HTTPS browser context.
 */
export async function prepareNativeRauthyLogin(signal:AbortSignal):Promise<NativePreparation>{
  if(signal.aborted)return {kind:"unavailable",code:"NATIVE_PREPARATION_CANCELLED"}
  const startedAt=Date.now(),startedMonotonic=performance.now()
  try{
    const begin=await fetch(CONTROL_PANEL_AUTH_API+"/start",{...REQUEST,signal})
    if(signal.aborted)return {kind:"unavailable",code:"NATIVE_PREPARATION_CANCELLED"}
    if(begin.status!==201){
      const code=await readBoundedErrorCode(begin,signal,"NATIVE_UNAVAILABLE")
      if(signal.aborted)return {kind:"unavailable",code:"NATIVE_PREPARATION_CANCELLED"}
      return {kind:begin.status===403?"forbidden":"unavailable",code}
    }
    const expiresIn=nativeInitLifetime(await readBoundedJsonResponse(begin,signal,4096))
    if(expiresIn===null){
      return {kind:"invalid",code:"NATIVE_INIT_RESPONSE_INVALID"}
    }
    if(signal.aborted)return {kind:"unavailable",code:"NATIVE_PREPARATION_CANCELLED"}
    // Charge the whole round trip to the server TTL. Receiving a delayed
    // response must never renew a transaction created earlier on the server.
    const elapsed=performance.now()-startedMonotonic
    const expiresAt=Math.min(startedAt+expiresIn*1000,Date.now()+expiresIn*1000-elapsed)
    if(!Number.isFinite(elapsed)||elapsed<0||Date.now()>=expiresAt||Date.now()<startedAt)return {kind:"expired",code:"NATIVE_PREPARATION_EXPIRED"}
    return {kind:"prepared",expiresIn:expiresIn,expiresAt}
  }catch{
    return {kind:"unavailable",code:signal.aborted?"NATIVE_PREPARATION_CANCELLED":"NATIVE_NETWORK_UNAVAILABLE"}
  }
}
