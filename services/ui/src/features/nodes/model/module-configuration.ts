/** Browser/Serena configuration mirrors the bounded Node ModuleConfiguration contract. */
export interface BrowserConfiguration {
  external_enabled:boolean
  external_mcp_url:string
  call_timeout_seconds:number|null
  auto_disconnect_enabled:boolean
  idle_timeout_seconds:number
  profile_dir_name:string
  developer_access_enabled:boolean
}
export interface SerenaConfiguration {project_path:string;language_backend:'LSP'}
export interface RuntimePolicy {execution_timeout_seconds:number|null;web_max_tabs:number|null;web_tab_idle_seconds:number|null;terminal_idle_seconds:number|null}
export interface ModuleConfiguration {runtime_policy?:RuntimePolicy|null;browser?:BrowserConfiguration|null;serena?:SerenaConfiguration|null}

export function defaultConfiguration(module:string):ModuleConfiguration {
  if(module==='web')return {browser:{external_enabled:false,external_mcp_url:'',call_timeout_seconds:null,
    auto_disconnect_enabled:false,idle_timeout_seconds:300,profile_dir_name:'Default',developer_access_enabled:false}}
  if(module==='serena')return {serena:{project_path:'.',language_backend:'LSP'}}
  return {}
}
export function initialConfiguration(module:string,current?:ModuleConfiguration|null):ModuleConfiguration {
  const defaults=defaultConfiguration(module)
  if(module==='web')return {...current,browser:{...defaults.browser!,...(current?.browser??{})}}
  if(module==='serena')return {...current,serena:{...defaults.serena!,...(current?.serena??{})}}
  return {}
}
export function configurationValid(module:string,configuration:ModuleConfiguration):boolean {
  if(module==='serena'){
    const path=configuration.serena?.project_path
    return typeof path==='string'&&path.length>0&&path.length<=512&&!path.startsWith('/')&&
      !/[\\:\u0000-\u001f]/.test(path)&&!path.split('/').includes('..')&&configuration.serena?.language_backend==='LSP'
  }
  if(module==='web'){
    const browser=configuration.browser
    if(!browser)return false
    if(!browser.external_mcp_url)return !browser.external_enabled
    try{
      const url=new URL(browser.external_mcp_url)
      return browser.external_mcp_url.length<=2048&&url.protocol==='https:'&&!!url.hostname&&
        !url.username&&!url.password&&!url.hash&&(!url.port||url.port==='443')
    }catch{return false}
  }
  return true
}
