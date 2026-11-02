import {CONTROL_PANEL_AUTH_API} from "@/shared/config"
import {readBoundedJsonResponse,readBoundedErrorCode} from "@/shared/lib/transport"
import {checkNativePrelogin} from "./native-prelogin-control"
import {prepareNativeRauthyLogin} from "./native-rauthy"
import {solveRauthyPow,validRauthyPowChallenge} from "../model/rauthy-pow"
import {decodeNativeSession,decodeNativeOtp,decodeNativeContinuation,decodeNativeFailure,nativeObject,nativeExact,type NativeLoginOutcome} from "../model/native-auth-protocol"

/** Rauthy owns identity. A successful first factor only creates an opaque
 * cookie-bound browser session. It is NOT a Platform User/Project/Cedar grant.
 */
export type {NativeLoginOutcome} from "../model/native-auth-protocol"

const requestHeaders={Accept:"application/json","Content-Type":"application/json"}
const postSettings={
  method:"POST",credentials:"same-origin",mode:"same-origin",cache:"no-store",
  referrerPolicy:"no-referrer",redirect:"error",headers:requestHeaders,
} as const
function validCredentials(email:string,password:string):boolean{
  return email.length>=3&&email.length<=320&&email.split("@").length===2&&
    Array.from(email).every(character=>character.charCodeAt(0)>32&&character.charCodeAt(0)!==127)&&email===email.trim()&&
    password.length>=1&&password.length<=256
}
function secureBrowser():boolean{
  return typeof window!=="undefined"&&(window.location.protocol==="https:"||
    (window.location.protocol==="http:"&&window.location.origin==="http://127.0.0.1"))&&
    window.isSecureContext===true
}
/** Provider's public challenge expires independently of the Init cookie.
 * A rollback in the device wall clock cannot extend a PoW already observed.
 * Keep a small delivery margin so a worker finishing at the boundary never
 * triggers a doomed password submission.
 */
export function usableNativePowDeadline(
  challenge:string,
  observedWallMs:number,
  observedMonotonicMs:number,
  nowWallMs:number,
  nowMonotonicMs:number,
):boolean{
  const match=/^1:\d{2}:(\d{10}):/.exec(challenge)
  if(!match||![observedWallMs,observedMonotonicMs,nowWallMs,nowMonotonicMs]
    .every(Number.isFinite))return false
  const elapsed=nowMonotonicMs-observedMonotonicMs
  if(elapsed<0)return false
  const expires=Number(match[1])*1000
  return expires-Math.max(nowWallMs,observedWallMs+elapsed)>1500
}
type NativeWork = {kind:"ready";work:string}|{kind:"failed";outcome:NativeLoginOutcome}
const cancelled:NativeLoginOutcome={kind:"cancelled",code:"NATIVE_LOGIN_CANCELLED"}
const uncertain:NativeLoginOutcome={kind:"uncertain",code:"NATIVE_LOGIN_RESULT_UNCERTAIN"}
function dispatchFailure(dispatched:boolean):NativeLoginOutcome{
  return dispatched?uncertain:{kind:"unavailable",code:"NATIVE_LOGIN_UNAVAILABLE"}
}

/** Reserve and solve one challenge. No credentials are dispatched here. */
async function prepareNativeWork(expiresAt:number,signal:AbortSignal):Promise<NativeWork>{
  const response=await fetch(CONTROL_PANEL_AUTH_API+"/pow",{...postSettings,signal,body:"{}"})
  if(signal.aborted)return {kind:"failed",outcome:cancelled}
  if(response.status!==200){
    const code=await readBoundedErrorCode(response,signal,"NATIVE_POW_UNAVAILABLE")
    return {kind:"failed",outcome:{kind:response.status===401?"expired":"unavailable",code}}
  }
  const data=nativeObject(await readBoundedJsonResponse(response,signal,4096))
  const challenge=data?.challenge
  if(!data||!nativeExact(data,["challenge","authenticated"])||data.authenticated!==false||!validRauthyPowChallenge(challenge)){
    return {kind:"failed",outcome:{kind:"unavailable",code:"NATIVE_POW_INVALID"}}
  }
  const observedWall=Date.now(),observedMonotonic=performance.now()
  const solution=await solveRauthyPow(challenge,signal)
  if(signal.aborted||solution.kind==="cancelled")return {kind:"failed",outcome:cancelled}
  if(solution.kind!=="solved")return {kind:"failed",outcome:{kind:"unavailable",code:"NATIVE_POW_UNAVAILABLE"}}
  if(!usableNativePowDeadline(challenge,observedWall,observedMonotonic,Date.now(),performance.now())||Date.now()>=expiresAt){
    return {kind:"failed",outcome:{kind:"expired",code:"NATIVE_LOGIN_EXPIRED"}}
  }
  return {kind:"ready",work:solution.work}
}

/** Decode a dispatched attempt without retrying the consumed credentials. */
async function readNativeLoginReply(reply:Response,signal:AbortSignal):Promise<NativeLoginOutcome>{
  if(signal.aborted)return uncertain
  if(reply.status===200||reply.status===202){
    const body=await readBoundedJsonResponse(reply,signal,4096)
    if(signal.aborted)return uncertain
    return reply.status===200?decodeNativeSession(body):decodeNativeOtp(body)
  }
  if(reply.status===409)return decodeNativeContinuation(await readBoundedJsonResponse(reply,signal,4096))
  const code=await readBoundedErrorCode(reply,signal,"NATIVE_LOGIN_UNAVAILABLE")
  return signal.aborted?uncertain:decodeNativeFailure(reply.status,code)
}
/** Execute exactly one explicit password attempt. NO automatic replay of
 * consumed PoW/credentials. Cancel/timeout after a dispatched first factor
 * returns uncertain; the UI must perform a separate signed session read.
 *
 * This function never stores or logs email, password, challenge, session
 * cookies, provider tokens or credential responses.
 */
export async function submitNativePasswordLogin(
  email:string,password:string,signal:AbortSignal,
):Promise<NativeLoginOutcome>{
  if(signal.aborted)return {kind:"cancelled",code:"NATIVE_LOGIN_CANCELLED"}
  if(!secureBrowser())return {kind:"unavailable",code:"NATIVE_SECURE_CONTEXT_REQUIRED"}
  if(!validCredentials(email,password))return {kind:"rejected",code:"NATIVE_CREDENTIALS_INVALID"}
  const protocol=await checkNativePrelogin(signal)
  if(signal.aborted)return {kind:"cancelled",code:"NATIVE_LOGIN_CANCELLED"}
  if(protocol.kind!=="supported")return {kind:"unavailable",code:protocol.code}
  const init=await prepareNativeRauthyLogin(signal)
  if(signal.aborted)return {kind:"cancelled",code:"NATIVE_LOGIN_CANCELLED"}
  if(init.kind!=="prepared")return {kind:init.kind==="expired"?"expired":"unavailable",code:init.code}
  let credentialDispatched=false
  try{
    const work=await prepareNativeWork(init.expiresAt,signal)
    if(work.kind==="failed")return work.outcome
    const body=JSON.stringify({email,password,pow:work.work})
    if(new TextEncoder().encode(body).length>8192)return {kind:"rejected",code:"NATIVE_REQUEST_INVALID"}
    if(signal.aborted)return cancelled
    credentialDispatched=true
    const reply=await fetch(CONTROL_PANEL_AUTH_API+"/first-factor",{...postSettings,signal,body})
    return await readNativeLoginReply(reply,signal)
  }catch{
    return dispatchFailure(credentialDispatched)
  }
}
