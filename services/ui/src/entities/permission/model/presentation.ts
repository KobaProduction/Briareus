import {HAND_EFFECT_ACTIONS,type HandEffectScope} from '@/shared/lib/hand-effect-scope'
export interface PermissionGroup {id:string;title:string;actions:string[];operations:string[];tools:string[];system:boolean}
const moduleTitles:Record<string,string>={files:'Файлы',terminal:'Терминал',web:'Браузер',reverse:'Анализ',svc:'Системы контроля версий',infrastructure:'Инфраструктура',integrations:'Подключения',variables:'Переменные',agents:'Агенты',project:'Система'}
const actionTitles:Record<string,string>={read:'Чтение',write:'Запись',execute:'Выполнение',access:'Доступ',import:'Импорт',manage:'Управление',use:'Использование'}
/** Formats current owner evidence. Does not infer grants from a module name. */
export function presentPermissions(operations:readonly string[],scopes:readonly HandEffectScope[]):PermissionGroup[]{
  const groups=new Map<string,PermissionGroup>()
  for(const operation of operations){
    const effects=scopes.filter(scope=>scope.action===operation)
    const candidates=Object.entries(HAND_EFFECT_ACTIONS).filter(([,actions])=>(actions as readonly string[]).includes(operation)).map(([hand])=>hand)
    const modules=effects.length?[...new Set(effects.map(scope=>scope.hand))]:[candidates.length===1?candidates[0]!:operation.split('.')[0]!]
    for(const id of modules){
      if(!groups.has(id))groups.set(id,{id,title:moduleTitles[id]||id,actions:[],operations:[],tools:[],system:operation==='project.metadata.read'})
      const group=groups.get(id)!,action=actionTitles[operation.split('.').at(-1)!]||operation
      if(!group.actions.includes(action))group.actions.push(action)
      if(!group.operations.includes(operation))group.operations.push(operation)
      for(const scope of effects.filter(scope=>scope.hand===id))if(!group.tools.includes(scope.tool))group.tools.push(scope.tool)
    }
  }
  return [...groups.values()]
}
export function shortIdentifier(id:string){return id.length>18?id.slice(0,8)+'…'+id.slice(-6):id}
