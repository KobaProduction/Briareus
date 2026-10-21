import {describe,it,expect} from 'bun:test'
import {effectScope} from 'vue'
import {relativeTime,timeUpdateIntervalMs,usePresentationClock} from '../src/shared/lib/presentation-clock'

describe('one clock for presentation only',()=>{
  it('shares one scheduled tick and releases it after the last consumer',()=>{
    const realTimeout=globalThis.setTimeout,realClear=globalThis.clearTimeout
    const jobs=new Map<number,()=>void>();let id=0
    globalThis.setTimeout=((fn:()=>void)=>{jobs.set(++id,fn);return id}) as unknown as typeof setTimeout
    globalThis.clearTimeout=((key:number)=>{jobs.delete(key)}) as typeof clearTimeout
    const first=effectScope(),second=effectScope()
    try{
      const a=first.run(()=>usePresentationClock()),b=second.run(()=>usePresentationClock())
      expect(a).toBe(b);expect(jobs.size).toBe(1)
      timeUpdateIntervalMs.value=5000;expect(jobs.size).toBe(1)
      first.stop();expect(jobs.size).toBe(1)
      second.stop();expect(jobs.size).toBe(0)
    }finally{first.stop();second.stop();timeUpdateIntervalMs.value=1000;globalThis.setTimeout=realTimeout;globalThis.clearTimeout=realClear}
  })
  it('formats elapsed and future time without altering the timestamp',()=>{
    const stamp='2026-10-19T00:00:00Z',now=Date.parse(stamp)
    expect(relativeTime(stamp,now+3000)).toBe('3 с назад')
    expect(relativeTime(stamp,now+83000)).toBe('1 мин 23 с назад')
    expect(relativeTime(stamp,now-5000)).toBe('через 5 с')
    expect(relativeTime('invalid',now)).toBe('—')
  })
})
