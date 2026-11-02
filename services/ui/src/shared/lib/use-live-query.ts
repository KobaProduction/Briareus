import {onScopeDispose,watch} from 'vue'
import {eventBus,type BusEvent} from '@/shared/events'

/** Coalesces invalidations, including events arriving during an active read.
 * Reads recover after reconnect/replay gaps; writes are never replayed here. */
export function useLiveQuery(read:()=>Promise<void>,options:{enabled:()=>boolean;paused?:()=>boolean;topics:string[];accept?:(event:BusEvent)=>boolean}){
  let dirty=false,running=false,disposed=false
  async function flush(){
    if(disposed||running||!dirty||!options.enabled()||options.paused?.())return
    dirty=false;running=true
    try{await read()}catch{/* The read adapter owns its visible error state. */}finally{running=false;if(dirty&&!disposed)queueMicrotask(()=>{void flush()})}
  }
  function invalidate(){dirty=true;void flush()}
  const stops=options.topics.map(topic=>eventBus.subscribe(topic,event=>{if(!options.accept||options.accept(event))invalidate()}))
  stops.push(eventBus.subscribe('system.notifications',event=>{if(event.type==='resync.required'||event.type==='source.recovered')invalidate()}))
  stops.push(eventBus.subscribe('connection.state',event=>{if(event.type==='connected')invalidate()}))
  watch(options.enabled,value=>{if(value)invalidate()},{immediate:true})
  if(options.paused)watch(options.paused,value=>{if(!value)void flush()})
  onScopeDispose(()=>{disposed=true;stops.forEach(stop=>{stop()})})
  return {invalidate}
}
