/** Runtime component labels; logical module membership comes from Resources. */
export function moduleName(key:string,fallback=key){
 return ({files:'Файлы',terminal:'Терминал',web:'Web',serena:'Serena · LSP',reverse:'Анализ'} as Record<string,string>)[key]??fallback
}
export function moduleLabel(key:string,fallback=key){
 const name=moduleName(key,fallback)
 if(key==='serena')return 'Разработка / '+name
 return name
}
export function placementStateSummary(placements:{module:string;state:string}[],modules:string[]){
 const items=placements.filter(item=>modules.includes(item.module))
 if(!items.length)return 'Не размещён'
 const labels:Record<string,string>={ready:'Работает',failed:'Ошибка',pending:'В очереди',updating:'Запускается',disabled:'Отключён'}
 return [...new Set(items.map(item=>item.state))].map(state=>`${labels[state]??state}: ${items.filter(item=>item.state===state).length}`).join(' · ')
}
