import {CONTROL_PANEL_AUTH_API} from "@/shared/config/control-panel-api"
import {readBoundedJsonResponse} from "@/shared/lib/bounded-json-response"

export async function nativeOtp(step:"start"|"finish",value:number|string,signal:AbortSignal):Promise<boolean>{
  const response=await fetch(`${CONTROL_PANEL_AUTH_API}/otp/${step}`,{
    method:"POST",credentials:"same-origin",mode:"same-origin",redirect:"error",cache:"no-store",referrerPolicy:"no-referrer",signal,
    headers:{Accept:"application/json","Content-Type":"application/json"},
    body:JSON.stringify(step==="start"?{method_index:value}:{otp_code:value}),
  })
  if(signal.aborted||response.status!==(step==="start"?202:200))return false
  const result=await readBoundedJsonResponse(response,signal,4096) as Record<string,unknown>
  return step==="start"?result.stage==="otp_code_pending"&&result.authenticated===false:
    result.stage==="authenticated"&&result.authenticated===true&&result.authority==="rauthy"
}
