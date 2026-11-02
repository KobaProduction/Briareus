import {CONTROL_PANEL_AUTH_API} from "@/shared/config"
import {readBoundedJsonResponse} from "@/shared/lib/transport"
import {validNativeCapabilities,nativeObject} from "../model/native-auth-protocol"
/** Native prelogin controls from the Backend-owned rauthy-native-v1 protocol.
 * These endpoints never collect credentials or establish Rauthy/Platform identity.
 * They are safe to call only in the existing same-origin HTTPS browser.
 */
export type NativePreloginCapabilities =
  | {kind:"supported"}
  | {kind:"unavailable"|"invalid"|"forbidden";code:string}
export type NativeCancellation =
  | {kind:"cancelled"}
  | {kind:"unavailable"|"forbidden";code:string}

/** Preserve this endpoint's strict media, length and error-code profile while
 * sharing the abort-aware body reader with the other native endpoints. */
async function boundedNativeJson(reply:Response,signal:AbortSignal):Promise<unknown>{
  const media=reply.headers.get("content-type")?.split(";",1)[0]?.trim()
  const size=reply.headers.get("content-length")
  if(media!=="application/json")throw Error("unexpected native JSON media")
  if(size!==null&&(!/^\d{1,6}$/.test(size)||Number(size)>4096))throw Error("native reply too large")
  return readBoundedJsonResponse(reply,signal,4096,true)
}
async function serverError(response:Response,signal:AbortSignal):Promise<string>{
  try{
    const payload=nativeObject(await boundedNativeJson(response,signal))
    const code=nativeObject(payload?.error)?.code
    return typeof code==="string"&&/^[A-Z][A-Z_]{0,63}$/.test(code)?code:"NATIVE_UNAVAILABLE"
  }catch{return "NATIVE_UNAVAILABLE"}
}

/** Accept only the two exact advertised Backend v1 profiles:
 * password-only [] and password+OTP ["otp"]. An OTP capability describes
 * a possible server continuation, NEVER proof the specific user needs OTP,
 * has supplied a valid password or owns a Platform role. All other names,
 * duplicate entries and missing fields remain rejected before Init.
 */
export async function checkNativePrelogin(signal:AbortSignal):Promise<NativePreloginCapabilities>{
  if(signal.aborted)return {kind:"unavailable",code:"NATIVE_CAPABILITIES_CANCELLED"}
  try{
    const response=await fetch(CONTROL_PANEL_AUTH_API+"/capabilities",{
      method:"GET",credentials:"same-origin",mode:"same-origin",cache:"no-store",
      redirect:"error",referrerPolicy:"no-referrer",signal,
      headers:{Accept:"application/json"},
    })
    if(signal.aborted)return {kind:"unavailable",code:"NATIVE_CAPABILITIES_CANCELLED"}
    if(response.status!==200){
      const code=await serverError(response,signal)
      if(signal.aborted)return {kind:"unavailable",code:"NATIVE_CAPABILITIES_CANCELLED"}
      return {kind:response.status===403?"forbidden":"unavailable",code}
    }
    const body=await boundedNativeJson(response,signal)
    if(!validNativeCapabilities(body)){
      return {kind:"invalid",code:"NATIVE_CAPABILITIES_INVALID"}
    }
    if(signal.aborted)return {kind:"unavailable",code:"NATIVE_CAPABILITIES_CANCELLED"}
    return {kind:"supported"}
  }catch{return {kind:"unavailable",code:"NATIVE_CAPABILITIES_UNAVAILABLE"}}
}

/** Only explicit user cancellation; never revoke a completed signed-in session.
 * A timeout is uncertain: the UI must not report that cleanup succeeded. */
export async function cancelNativePrelogin(signal:AbortSignal):Promise<NativeCancellation>{
  if(signal.aborted)return {kind:"unavailable",code:"NATIVE_CANCEL_CANCELLED"}
  try{
    const response=await fetch(CONTROL_PANEL_AUTH_API+"/cancel",{
      method:"POST",credentials:"same-origin",mode:"same-origin",cache:"no-store",
      redirect:"error",referrerPolicy:"no-referrer",signal,
      headers:{Accept:"application/json","Content-Type":"application/json"},body:"{}",
    })
    if(signal.aborted)return {kind:"unavailable",code:"NATIVE_CANCEL_UNCERTAIN"}
    if(response.status===204)return {kind:"cancelled"}
    const code=await serverError(response,signal)
    if(signal.aborted)return {kind:"unavailable",code:"NATIVE_CANCEL_UNCERTAIN"}
    return {kind:response.status===403?"forbidden":"unavailable",code}
  }catch{return {kind:"unavailable",code:"NATIVE_CANCEL_UNCERTAIN"}}
}
