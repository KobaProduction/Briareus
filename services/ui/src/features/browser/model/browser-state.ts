export interface BrowserTab {page_id:string;title:string;url:string;label?:string}
export interface BrowserElement {ref:string;tag?:string;role?:string;name?:string;text?:string;type?:string;value?:string;disabled?:boolean}
export function editableBrowserElement(element:BrowserElement):boolean {
  return element.tag==='textarea'||element.tag==='input'&&!['file','checkbox','radio','submit','button','reset','image','hidden'].includes((element.type??'').toLowerCase())
}
export function mergeBrowserInputs(previous:BrowserElement[],next:BrowserElement[],drafts:Record<string,string>,samePage:boolean):Record<string,string>{
  const result:Record<string,string>={}
  for(const element of next){
    if(!editableBrowserElement(element)||(element.type??'').toLowerCase()==='password')continue
    const old=previous.find(item=>item.ref===element.ref&&item.tag===element.tag&&item.type===element.type&&item.name===element.name)
    const dirty=samePage&&old&&Object.prototype.hasOwnProperty.call(drafts,element.ref)&&drafts[element.ref]!==old.value
    result[element.ref]=dirty?drafts[element.ref]!:(element.value??'')
  }
  return result
}
export function browserValue(raw:any):any {
  if(raw?.isError)throw new Error(raw.content?.find((c:any)=>c.type==='text')?.text||'BROWSER_TOOL_FAILED')
  if(raw?.structuredContent){let value=raw.structuredContent;while(value&&typeof value==='object'&&Object.keys(value).length===1&&'result' in value)value=value.result;return value}
  for(const entry of raw?.content??[])if(entry.type==='text'){try{return JSON.parse(entry.text)}catch{/* textual content */}}
  return raw
}
export function transportLabel(url:string):string {
  try {const protocol=new URL(url).protocol;return protocol==='https:'?'HTTPS · шифрованное соединение':protocol==='http:'?'HTTP · без шифрования':'Служебная страница'}catch{return 'Адрес не определён'}
}
export function reconcileSelection(tabs:BrowserTab[],selected:string):string {
  return tabs.some(tab=>tab.page_id===selected)?selected:(tabs[0]?.page_id??'')
}
