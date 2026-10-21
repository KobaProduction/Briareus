/** Port of HTTP Bridge shared/events/bus.ts, repair b89c5f6.
 * Same-origin authenticated WebSocket, reconnect generations and scoped
 * listeners; retired SSE/mock transports and Admin API URLs are removed.
 */
import {reactive,readonly} from "vue"
import {jsonCodec,RpcError} from "./protocol"
export interface BusEvent {id?:string;topic:string;type:string;occurredAt:string;data:unknown}
const history=reactive<BusEvent[]>([])
let historySequence=0
type Handler=(event:BusEvent)=>void
const handlers=new Map<string,Set<Handler>>()
const state=reactive({status:"idle" as "idle"|"connecting"|"connected"|"reconnecting"|"error",
  sessionActive:false,lastRemoteEventAt:"",retryAttempt:0,latencyMs:null as number|null,received:0,toolCalls:0,
  reconnects:0,lastDisconnectCode:null as number|null,lastSequence:0,deliveryGaps:0,
  metricsEnabled:false,subscriptions:[] as string[],sources:{} as Record<string,{source:string;projectId:string|null;status:"connected"|"unavailable";lastEventAt:string}>})
let socket:WebSocket|null=null,generation=0,retry=0,scope:string|null=null
let reconnect:ReturnType<typeof setTimeout>|null=null,heartbeat:ReturnType<typeof setInterval>|null=null
let pingStarted=0,lastReceived=0
let lastCursor:string|null=null
const pending=new Map<string,{resolve:(value:unknown)=>void;reject:(error:Error)=>void;cleanup:()=>void}>()
function rejectPending(){for(const call of pending.values()){call.cleanup();call.reject(new Error("Соединение прервано; результат команды не подтверждён"))}pending.clear()}
function request<T=unknown>(method:string,params:Record<string,unknown>={},signal?:AbortSignal):Promise<T>{
  if(socket?.readyState!==WebSocket.OPEN||pending.size>=32||signal?.aborted)return Promise.reject(new Error("Нет соединения с сервером"))
  const current=socket,id=crypto.randomUUID()
  return new Promise<T>((resolve,reject)=>{
    const cancel=()=>{const call=pending.get(id);if(call){pending.delete(id);call.cleanup();reject(new Error("Ожидание ответа отменено; результат команды не подтверждён"))}}
    const timeout=setTimeout(cancel,method==='analysis.command'?30000:['browser.command','terminal.command'].includes(method)?20000:8000)
    const cleanup=()=>{clearTimeout(timeout);signal?.removeEventListener('abort',cancel)}
    pending.set(id,{resolve:value=>resolve(value as T),reject,cleanup})
    signal?.addEventListener('abort',cancel,{once:true})
    try{current.send(jsonCodec.encode({jsonrpc:'2.0',id,method,params}))}catch{cancel()}
  })
}
const seen=new Set<string>()
const topics=["platform.context","mcp.calls","management.events","browser.runtime","system.metrics","system.notifications","access.sessions"]
const subscribedTopics=()=>topics.filter(topic=>topic!=='system.metrics'||state.metricsEnabled)
async function syncSubscriptions(){const desired=subscribedTopics(),excluded=topics.filter(topic=>!desired.includes(topic));if(excluded.length)await request('events.unsubscribe',{topics:excluded});return request<{topics:string[]}>('events.subscribe',{topics:desired,cursor:lastCursor})}
async function setMetricsEnabled(enabled:boolean){const previous=state.metricsEnabled;state.metricsEnabled=enabled;try{if(socket?.readyState===WebSocket.OPEN){const reply=await syncSubscriptions();state.subscriptions=reply.topics.filter(topic=>topics.includes(topic))}}catch(error){state.metricsEnabled=previous;throw error}}
function dispatch(event:BusEvent){
  if(!["platform.context","connection.state","session.refresh"].includes(event.topic)){
    history.unshift({...event,id:event.id??`receipt:${++historySequence}`});if(history.length>200)history.pop()
  }
  for(const listener of handlers.get(event.topic)??[]){try{listener(event)}catch{console.warn("panel.event_listener_failed",event.topic)}}
}
function status(value:typeof state.status){if(state.status===value)return;state.status=value;dispatch({topic:"connection.state",type:value,occurredAt:new Date().toISOString(),data:null})}
function close(){
  generation++;rejectPending();if(reconnect)clearTimeout(reconnect);reconnect=null
  if(heartbeat)clearInterval(heartbeat);heartbeat=null
  const current=socket;socket=null;current?.close();state.latencyMs=null;state.subscriptions=[]
}
function ping(){if(socket?.readyState!==WebSocket.OPEN)return;pingStarted=performance.now();void request('system.ping').then(()=>{state.latencyMs=Math.round(performance.now()-pingStarted)}).catch(()=>{})}
function schedule(){
  if(!state.sessionActive)return
  if(reconnect)clearTimeout(reconnect)
  status("reconnecting");state.retryAttempt=++retry
  reconnect=setTimeout(connect,Math.min(15000,500*2**Math.min(retry,5))+Math.random()*250)
}
function connect(){
  reconnect=null;if(!state.sessionActive||socket)return
  status(retry?"reconnecting":"connecting")
  const current=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/api/v1/events${scope?'?project_uuid='+encodeURIComponent(scope):''}`)
  const run=++generation;socket=current
  let streamId:string|null=null,sequence=0
  const isCurrent=()=>socket===current&&generation===run
  current.onopen=()=>{if(!isCurrent())return;lastReceived=Date.now();void syncSubscriptions().then(reply=>{if(isCurrent())state.subscriptions=reply.topics.filter(topic=>topics.includes(topic))}).catch(()=>{if(isCurrent())current.close()});ping();heartbeat=setInterval(()=>{if(!isCurrent())return;if(Date.now()-lastReceived>35000)current.close();else ping()},15000)}
  current.onmessage=event=>{
    if(!isCurrent())return
    try{
      const wire=jsonCodec.decode(event.data)
      const message=(wire.jsonrpc==='2.0'&&wire.method==='events.deliver'?wire.params:wire) as Record<string,any>
      if(!message||typeof message!=="object"||Array.isArray(message))throw new Error("Invalid event")
      lastReceived=Date.now();state.received++;state.lastRemoteEventAt=new Date().toISOString()
      if(message.jsonrpc==='2.0'&&typeof message.id==='string'){
        const call=pending.get(message.id)
        if(call){pending.delete(message.id);call.cleanup();if(message.error)call.reject(new RpcError(String(message.error.message??'UNAVAILABLE'),message.error.data?.uncertain===true,typeof message.error.data?.uncertain==='boolean'));else call.resolve(message.result)}
        return
      }
      if(typeof message.stream_id==='string'&&Number.isSafeInteger(message.sequence)){
        if(message.sequence!==(streamId===message.stream_id?sequence+1:1)){
          state.deliveryGaps++
          dispatch({topic:'system.notifications',type:'resync.required',occurredAt:state.lastRemoteEventAt,data:{reason:'delivery.gap'}})
        }
        streamId=message.stream_id;sequence=message.sequence;state.lastSequence=sequence
      }
      if(typeof message.event_id==="string"){
        if(seen.has(message.event_id))return
        seen.add(message.event_id);if(seen.size>2000)seen.delete(seen.values().next().value!)
      }
      if(typeof message.cursor==="string"&&/^\d+-\d+$/.test(message.cursor)){
        const number=(cursor:string)=>{const parts=cursor.split('-');return [BigInt(parts[0]!),BigInt(parts[1]!)] as const}
        const next=number(message.cursor),previous=lastCursor?number(lastCursor):null
        if(!previous||next[0]>previous[0]||(next[0]===previous[0]&&next[1]>previous[1]))lastCursor=message.cursor
      }
      if(message.topic==="system.notifications"&&["source.connected","source.recovered","source.unavailable"].includes(message.type)
        &&message.data&&typeof message.data.source==="string"){
        const data=message.data,key=data.source+':'+(data.project_id??'')
        state.sources[key]={source:data.source,projectId:data.project_id??null,status:message.type==="source.unavailable"?"unavailable":"connected",lastEventAt:state.lastRemoteEventAt}
      }
      if(message.type==="session.refresh"){dispatch({topic:"session.refresh",type:"refresh",occurredAt:state.lastRemoteEventAt,data:null});return}
      if(message.topic==="platform.context"&&message.type==="snapshot"){retry=0;state.retryAttempt=0;status("connected")}
      if(message.topic==="mcp.calls"&&message.type==="call.started")state.toolCalls++
      if(typeof message.topic==="string"&&typeof message.type==="string")dispatch({id:message.event_id,topic:message.topic,type:message.type,occurredAt:typeof message.occurredAt==="string"?message.occurredAt:state.lastRemoteEventAt,data:message.data})
    }catch{status("error");current.close(1008)}
  }
  current.onclose=event=>{
    if(!isCurrent())return
    state.reconnects++;state.lastDisconnectCode=event.code
    socket=null;rejectPending();if(heartbeat)clearInterval(heartbeat);heartbeat=null
    if(event.code===4401)dispatch({topic:"session.refresh",type:"refresh",occurredAt:new Date().toISOString(),data:null})
    if(event.code===4403){status("error");dispatch({topic:"session.denied",type:"denied",occurredAt:new Date().toISOString(),data:null});return}
    schedule()
  }
  current.onerror=()=>{if(isCurrent())status("reconnecting")}
}
function subscribe(topic:string,handler:Handler){let set=handlers.get(topic);if(!set){set=new Set();handlers.set(topic,set)}set.add(handler);return ()=>{set?.delete(handler);if(!set?.size)handlers.delete(topic)}}
function setSessionActive(active:boolean){state.sessionActive=active;if(!active){state.metricsEnabled=false;close();status("idle");state.toolCalls=0;state.received=0;state.lastRemoteEventAt="";state.sources={};lastCursor=null;seen.clear();history.splice(0);return}connect()}
function setScope(value:string|null){if(value===scope)return;scope=value;lastCursor=null;seen.clear();state.sources={};history.splice(0);close();connect()}
export const eventBus={setMetricsEnabled,state:readonly(state),history:readonly(history),subscribe,setSessionActive,setScope,ping,request}
if(import.meta.hot)import.meta.hot.dispose(()=>{close();handlers.clear()})
