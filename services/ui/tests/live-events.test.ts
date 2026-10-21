import {afterEach,beforeEach,describe,expect,it} from 'bun:test'
import {effectScope,nextTick,ref} from 'vue'
import {eventBus} from '../src/shared/events/bus'
import {useLiveQuery} from '../src/shared/lib/use-live-query'
import {oidcPagesForRole} from '../src/features/platform/model/oidc-view-routing'

const originalSocket=globalThis.WebSocket
const originalLocation=Object.getOwnPropertyDescriptor(globalThis,'location')
class SocketFixture{
  static OPEN=1
  static current:SocketFixture
  requests:{method:string;params:{topics?:string[]}}[]=[]
  readyState=1
  onopen:(()=>void)|null=null
  onmessage:((event:{data:string})=>void)|null=null
  onclose:((event:{code:number})=>void)|null=null
  onerror:(()=>void)|null=null
  constructor(){SocketFixture.current=this}
  send(wire:string){const request=JSON.parse(wire);this.requests.push(request);queueMicrotask(()=>this.onmessage?.({data:JSON.stringify({jsonrpc:'2.0',id:request.id,result:{topics:[]}})}))}
  close(){this.readyState=3;this.onclose?.({code:1000})}
  deliver(sequence:number,topic:string,type:string){this.onmessage?.({data:JSON.stringify({jsonrpc:'2.0',method:'events.deliver',params:{stream_id:'test-stream',sequence,topic,type,data:{},occurredAt:'2026-10-19T00:00:00Z'}})})}
}
const tick=async()=>{await nextTick();await new Promise(resolve=>setTimeout(resolve,0))}
beforeEach(()=>{
  globalThis.WebSocket=SocketFixture as unknown as typeof WebSocket
  Object.defineProperty(globalThis,'location',{configurable:true,value:{host:'127.0.0.1',protocol:'http:'}})
  eventBus.setSessionActive(true);SocketFixture.current.onopen?.();SocketFixture.current.deliver(1,'platform.context','snapshot')
})
afterEach(()=>{
  eventBus.setSessionActive(false);globalThis.WebSocket=originalSocket
  if(originalLocation)Object.defineProperty(globalThis,'location',originalLocation);else Reflect.deleteProperty(globalThis,'location')
})
describe('live reads and recovery',()=>{
  it('keeps optional system metrics off without dropping application subscriptions',async()=>{
    await tick()
    const requested=()=>SocketFixture.current.requests.filter(item=>item.method==='events.subscribe').at(-1)!.params.topics!
    expect(requested()).not.toContain('system.metrics')
    expect(requested()).toContain('management.events')
    await eventBus.setMetricsEnabled(true)
    expect(requested()).toContain('system.metrics')
    await eventBus.setMetricsEnabled(false)
    expect(requested()).not.toContain('system.metrics')
    expect(SocketFixture.current.requests.slice(-2).map(request=>request.method)).toEqual(['events.unsubscribe','events.subscribe'])
    expect(requested()).toContain('platform.context')
  })
  it('keeps an event received during a read and coalesces repeated events',async()=>{
    let calls=0,release:()=>void=()=>{}
    const first=new Promise<void>(resolve=>{release=resolve})
    const scope=effectScope()
    scope.run(()=>useLiveQuery(async()=>{calls++;if(calls===1)await first},{enabled:()=>true,topics:['management.events']}))
    SocketFixture.current.deliver(2,'management.events','team.rename')
    SocketFixture.current.deliver(3,'management.events','team.member.remove')
    expect(calls).toBe(1);release();await tick();expect(calls).toBe(2)
    scope.stop();SocketFixture.current.deliver(4,'management.events','team.rename');await tick();expect(calls).toBe(2)
  })
  it('recovers a delivery gap and waits for a running mutation before reading',async()=>{
    let calls=0
    const paused=ref(true),before=eventBus.state.deliveryGaps,scope=effectScope()
    scope.run(()=>useLiveQuery(async()=>{calls++},{enabled:()=>true,paused:()=>paused.value,topics:['management.events']}))
    SocketFixture.current.deliver(3,'system.metrics','process.snapshot')
    expect(eventBus.state.deliveryGaps).toBe(before+1);expect(calls).toBe(0)
    paused.value=false;await tick();expect(calls).toBe(1);scope.stop()
  })
  it('does not publish a reconnect transition on each authority snapshot',()=>{
    let connected=0
    const stop=eventBus.subscribe('connection.state',event=>{if(event.type==='connected')connected++})
    SocketFixture.current.deliver(2,'platform.context','snapshot')
    SocketFixture.current.deliver(3,'platform.context','snapshot')
    expect(connected).toBe(0);stop()
  })
  it('shows the users administration section only to the verified operator role',()=>{
    expect(oidcPagesForRole('user')).not.toContain('users')
    expect(oidcPagesForRole('operator')).toContain('users')
  })
})
