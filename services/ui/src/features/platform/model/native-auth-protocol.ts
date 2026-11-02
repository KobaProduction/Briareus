/** Exact public replies of the provider-owned native authentication protocol.
 * These facts never establish Platform membership or Cedar permissions.
 */
export type NativeLoginOutcome =
  | {kind:"session_issued"}
  | {kind:"otp_pending";methods:number[]}
  | {kind:"continuation_unavailable";stage:NativeContinuationStage}
  | {kind:"rejected"|"provider_rejected"|"unavailable"|"expired"|"rate_limited"|"cancelled"|"uncertain";code:string}

const unsupportedStages=["otp_pending","webauthn_pending","tos_pending","account_update_required","client_mfa_required"] as const
type NativeContinuationStage=typeof unsupportedStages[number]

export function nativeObject(value:unknown):Record<string,unknown>|null{
  return typeof value==="object"&&value!==null&&!Array.isArray(value)
    ?value as Record<string,unknown>:null
}
export function nativeExact(value:Record<string,unknown>,fields:readonly string[]):boolean{
  return Object.keys(value).length===fields.length&&
    fields.every(field=>Object.hasOwn(value,field))
}

export function decodeNativeSession(value:unknown):NativeLoginOutcome{
  const body=nativeObject(value)
  if(body&&nativeExact(body,["stage","authenticated","authority","platform_membership_verified","permissions"])&&
    body.stage==="authenticated"&&body.authenticated===true&&body.authority==="rauthy"&&
    body.platform_membership_verified===false&&Array.isArray(body.permissions)&&body.permissions.length===0){
    return {kind:"session_issued"}
  }
  return {kind:"uncertain",code:"NATIVE_LOGIN_RESPONSE_INVALID"}
}
function emailMethod(value:unknown,index:number):boolean{
  const method=nativeObject(value)
  return !!method&&nativeExact(method,["index","kind"])&&method.index===index&&method.kind==="email"
}
export function decodeNativeOtp(value:unknown):NativeLoginOutcome{
  const body=nativeObject(value),methods=body?.methods
  if(body&&nativeExact(body,["stage","authenticated","continuation_available","methods"])&&
    body.stage==="otp_pending"&&body.authenticated===false&&body.continuation_available===true&&
    Array.isArray(methods)&&methods.length>=1&&methods.length<=10&&methods.every(emailMethod)){
    return {kind:"otp_pending",methods:methods.map((_,index)=>index)}
  }
  return {kind:"unavailable",code:"NATIVE_CONTINUATION_INVALID"}
}
export function decodeNativeContinuation(value:unknown):NativeLoginOutcome{
  const body=nativeObject(value)
  if(body&&nativeExact(body,["stage","authenticated","continuation_available","restart_required"])&&
    body.authenticated===false&&body.continuation_available===false&&body.restart_required===true){
    const stage=unsupportedStages.find(candidate=>candidate===body.stage)
    if(stage)return {kind:"continuation_unavailable",stage}
  }
  return {kind:"unavailable",code:"NATIVE_CONTINUATION_INVALID"}
}
export function decodeNativeFailure(status:number,code:string):NativeLoginOutcome{
  if(status===401&&code==="NATIVE_PROVIDER_AUTH_REJECTED")return {kind:"provider_rejected",code}
  if(status===401||status===422)return {kind:"rejected",code}
  if(status===429)return {kind:"rate_limited",code}
  return {kind:"unavailable",code}
}

export function validNativeCapabilities(value:unknown):boolean{
  const body=nativeObject(value)
  if(!body||!nativeExact(body,["protocol","first_factor","pow","cancel","continuations"]))return false
  if(body.protocol!=="rauthy-native-v1"||body.first_factor!=="password"||body.pow!=="client-solved"||body.cancel!==true)return false
  const continuations=body.continuations
  return Array.isArray(continuations)&&(continuations.length===0||
    (continuations.length===1&&continuations[0]==="otp"))
}

export function nativeInitLifetime(value:unknown):number|null{
  const body=nativeObject(value)
  if(!body||!nativeExact(body,["stage","authenticated","expires_in"]))return null
  if(body.authenticated!==false||body.stage!=="first_factor_required")return null
  const ttl=body.expires_in
  return typeof ttl==="number"&&Number.isInteger(ttl)&&ttl>=1&&ttl<=300?ttl:null
}
