import {describe,it,expect} from 'bun:test'
import {startAnalysis} from '../src/features/analysis/model/start-operation'
import {RpcError} from '../src/shared/events/protocol'
describe('cold analysis start authority',()=>{
 it('retries only explicit zero-dispatch preparation with the same captured intent',async()=>{
  const intent={id:'original',args:{tool:'import'}};const seen:unknown[]=[];let poll=0,wait=0
  const result=await startAnalysis({start:async()=>{seen.push(intent);if(seen.length===1)throw new RpcError('ANALYSIS_PREPARING',false);return 'started'},resolve:async()=>{poll++;return 'resolved'},current:()=>true,preparing:()=>{},wait:async()=>{wait++}})
  expect(result).toBe('started');expect(seen).toEqual([intent,intent]);expect(wait).toBe(1);expect(poll).toBe(0)
 })
 it('resolves uncertain or undeclared replies without repeating an effect',async()=>{
  for(const error of [new RpcError('ANALYSIS_PREPARING',true),new RpcError('ANALYSIS_PREPARING',false,false),new Error('OUTCOME_UNKNOWN')]){
   let starts=0,resolves=0
   expect(await startAnalysis({start:async()=>{starts++;throw error},resolve:async()=>{resolves++;return 'receipt'},current:()=>true,preparing:()=>{},wait:async()=>{throw Error('must not wait')}})).toBe('receipt')
   expect(starts).toBe(1);expect(resolves).toBe(1)
  }
 })
 it('does not retry a definite authorization failure',async()=>{
  let resolves=0
  await expect(startAnalysis({start:async()=>{throw new RpcError('PERMISSION_DENIED',false)},resolve:async()=>{resolves++;return ''},current:()=>true,preparing:()=>{},wait:async()=>{}})).rejects.toThrow('PERMISSION_DENIED');expect(resolves).toBe(0)
 })
 it('stops preparation when its session becomes stale',async()=>{
  let current=true,starts=0
  await expect(startAnalysis({start:async()=>{starts++;throw new RpcError('ANALYSIS_PREPARING',false)},resolve:async()=>'',current:()=>current,preparing:()=>{},wait:async()=>{current=false}})).rejects.toThrow('отменена');expect(starts).toBe(1)
 })
})
