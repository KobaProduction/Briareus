import {computed,ref,watch,onScopeDispose,type Ref} from 'vue'
import {eventBus,type BusEvent} from '@/shared/events/bus'
interface Page {items:{event_id:string;topic:string;type:string;occurredAt:string;data:unknown}[];next_cursor:string|null;has_more:boolean;retention_gap:boolean;retention_limit:number}
export function useEventJournal(topics:Ref<string[]>,project:Ref<string|null>,identity:Ref<string>){
 const older=ref<BusEvent[]>([]),live=ref<BusEvent[]>([]),atTop=ref(true),busy=ref(false),error=ref(''),more=ref(true),gap=ref(false),retention=ref(20000)
 let cursor:string|null=null,generation=0,catching=false,disposed=false
 onScopeDispose(()=>{disposed=true;generation++})
 const pending=computed(()=>eventBus.history.filter(e=>topics.value.includes(e.topic)&&(project.value===null||(e.data as {project_id?:string})?.project_id===project.value)&&!live.value.some(row=>row.id===e.id)).length)
 const source=computed(()=>{const items=new Map<string,BusEvent>();for(const e of [...older.value,...live.value])items.set(e.id??e.occurredAt+e.topic+e.type,e);return [...items.values()].sort((a,b)=>b.occurredAt.localeCompare(a.occurredAt)||(b.id??'').localeCompare(a.id??''))})
 watch(()=>[eventBus.history[0]?.id,eventBus.history.length,atTop.value],()=>{if(atTop.value)live.value=[...eventBus.history]},{immediate:true})
 async function load(){if(busy.value||!more.value||eventBus.state.status!=='connected')return;busy.value=true;error.value='';const run=generation
  try{const page=await eventBus.request<Page>('events.history',{topics:topics.value,before:cursor,project_uuid:project.value,limit:100});if(run!==generation)return
   if(!Array.isArray(page.items)||typeof page.has_more!=='boolean'||page.has_more&&(!page.next_cursor||page.next_cursor===cursor))throw Error('Invalid journal cursor')
   older.value=[...new Map([...older.value,...page.items.map(e=>({id:e.event_id,topic:e.topic,type:e.type,occurredAt:e.occurredAt,data:e.data}))].map(e=>[e.id,e])).values()];cursor=page.next_cursor;more.value=page.has_more;gap.value ||= page.retention_gap;retention.value=page.retention_limit
  }catch{if(run===generation)error.value='Не удалось загрузить продолжение журнала.'}finally{if(run===generation)busy.value=false}
 }
 watch(()=>[topics.value.join(','),project.value,identity.value],()=>{generation++;older.value=[];live.value=[...eventBus.history];cursor=null;more.value=true;busy.value=false;error.value='';gap.value=false;void load()},{immediate:true})
 async function catchUp(){
  if(catching||busy.value||disposed)return
  if(!older.value.length){await load();return}
  catching=true;const run=generation,known=new Set(older.value.map(e=>e.id));let before:string|null=null
  try{
   while(run===generation&&!disposed){
    const page:Page=await eventBus.request('events.history',{topics:topics.value,before,project_uuid:project.value,limit:100})
    if(run!==generation||disposed)return
    if(!Array.isArray(page.items))throw Error('Invalid journal')
    const overlap=page.items.some(e=>known.has(e.event_id))
    older.value=[...new Map([...older.value,...page.items.map(e=>({id:e.event_id,topic:e.topic,type:e.type,occurredAt:e.occurredAt,data:e.data}))].map(e=>[e.id,e])).values()]
    gap.value ||= page.retention_gap
    if(overlap||!page.has_more)break
    if(!page.next_cursor||page.next_cursor===before)throw Error('Invalid journal cursor')
    before=page.next_cursor
   }
  }catch{if(run===generation)error.value='Не удалось восстановить пропущенные события.'}finally{catching=false}
 }
 watch(()=>eventBus.state.status,state=>{if(state==='connected')void catchUp()})
 const stop=eventBus.subscribe('system.notifications',event=>{if(event.type==='resync.required')void catchUp()})
 onScopeDispose(stop)
 function showLatest(){atTop.value=true;live.value=[...eventBus.history]}
 return {source,busy,error,more,gap,retention,atTop,pending,load,showLatest}
}
