import {describe,expect,it} from 'bun:test'
import {browserValue,reconcileSelection,transportLabel,editableBrowserElement,mergeBrowserInputs} from '../src/features/browser/model/browser-state'
describe('browser controls',()=>{
 it('clicks checkbox/radio/submit controls rather than filling them',()=>{for(const type of ['checkbox','radio','submit','button','file'])expect(editableBrowserElement({ref:'e1',tag:'input',type})).toBe(false)})
 it('preserves unsent text drafts while reflecting unchanged server values',()=>{
   const before=[{ref:'e1',tag:'input',name:'Email',value:'old'},{ref:'e2',tag:'input',name:'Title',value:'server'}]
   expect(mergeBrowserInputs(before,[{...before[0],value:'new'},{...before[1],value:'updated'}],{e1:'draft',e2:'server'},true)).toEqual({e1:'draft',e2:'updated'})
 })
 it('never initializes or retains a password from snapshots',()=>expect(mergeBrowserInputs([{ref:'e1',tag:'input',type:'password',value:'<redacted>'}],[{ref:'e1',tag:'input',type:'password',value:'<redacted>'}],{e1:'secret'},true)).toEqual({}))
 it('keeps selected tab when a background tab closes',()=>expect(reconcileSelection([{page_id:'selected',title:'',url:''}],'selected')).toBe('selected'))
 it('selects a surviving explicit ID after closing active tab',()=>expect(reconcileSelection([{page_id:'other',title:'',url:''}],'closed')).toBe('other'))
 it('does not treat plain HTTP as encrypted',()=>expect(transportLabel('http://example.com')).toContain('без шифрования'))
 it('reports HTTPS without asserting certificate identity',()=>expect(transportLabel('https://example.com')).toBe('HTTPS · шифрованное соединение'))
 it('unwraps real MCP JSON text',()=>expect(browserValue({content:[{type:'text',text:'{"page_id":"p"}'}]})).toEqual({page_id:'p'}))
 it('surfaces tool errors',()=>expect(()=>browserValue({isError:true,content:[{type:'text',text:'tab limit'}]})).toThrow('tab limit'))
})

