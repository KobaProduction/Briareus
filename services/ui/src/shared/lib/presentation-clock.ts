import {readonly,shallowRef,ref,watch,onScopeDispose} from 'vue'
export const timeUpdateIntervalMs=ref(1000)
const now=shallowRef(Date.now())
let consumers=0,timer:ReturnType<typeof setTimeout>|null=null
function stop(){if(timer!==null)clearTimeout(timer);timer=null}
function tick(){stop();now.value=Date.now();if(consumers&&!(typeof document!=='undefined'&&document.hidden))timer=setTimeout(tick,timeUpdateIntervalMs.value)}
watch(timeUpdateIntervalMs,()=>{if(consumers)tick()},{flush:'sync'})
if(typeof document!=='undefined')document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();else if(consumers)tick()})
/** One shared display clock, independent of network heartbeats and authority deadlines. */
export function usePresentationClock(){consumers++;if(consumers===1)tick();onScopeDispose(()=>{consumers--;if(!consumers)stop()});return readonly(now)}
export function relativeTime(value:string,clock:number){
  const date=Date.parse(value);if(!Number.isFinite(date))return '—'
  const seconds=Math.floor(Math.abs(clock-date)/1000)
  const text=seconds<60?seconds+' с':seconds<3600?Math.floor(seconds/60)+' мин '+seconds%60+' с':seconds<86400?Math.floor(seconds/3600)+' ч '+Math.floor(seconds%3600/60)+' мин':Math.floor(seconds/86400)+' д '+Math.floor(seconds%86400/3600)+' ч'
  return date>clock?'через '+text:text+' назад'
}

if(import.meta.hot)import.meta.hot.dispose(stop)
