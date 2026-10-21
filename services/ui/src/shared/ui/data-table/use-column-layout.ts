import {computed,ref,watch} from 'vue'
import type {DataTableColumn} from './types'
/** Preferences contain column keys only; never table records or authority. */
export function useColumnLayout(columns:()=>DataTableColumn[],key:()=>string){
  const order=ref<string[]>([]),explicitHidden=ref<string[]>([]),shown=ref<string[]>([])
  const hidden=computed(()=>[...new Set([...explicitHidden.value,...columns().filter(column=>column.defaultHidden&&!shown.value.includes(column.key)).map(column=>column.key)])])
  watch(key,value=>{
    order.value=[];explicitHidden.value=[];shown.value=[]
    try{const saved=JSON.parse(localStorage.getItem('briareus:columns:'+value)||'null');if(saved&&Array.isArray(saved.order)&&Array.isArray(saved.hidden)){order.value=saved.order.filter((k:unknown)=>typeof k==='string').slice(0,100);explicitHidden.value=saved.hidden.filter((k:unknown)=>typeof k==='string').slice(0,100);shown.value=Array.isArray(saved.shown)?saved.shown.filter((k:unknown)=>typeof k==='string').slice(0,100):[]}}catch{/* Browser preferences are optional. */}
  },{immediate:true})
  const ordered=computed(()=>{
    const ranks=new Map(order.value.map((id,index)=>[id,index]))
    return [...columns()].sort((a,b)=>(ranks.get(a.key)??1000)-(ranks.get(b.key)??1000))
  })
  const visible=computed(()=>{const selected=ordered.value.filter(column=>!hidden.value.includes(column.key));return selected.length?selected:ordered.value.slice(0,1)})
  function save(){try{localStorage.setItem('briareus:columns:'+key(),JSON.stringify({order:order.value,hidden:explicitHidden.value,shown:shown.value}))}catch{/* Memory preferences still work. */}}
  function toggle(id:string){
    if(hidden.value.includes(id)){explicitHidden.value=explicitHidden.value.filter(key=>key!==id);shown.value=[...new Set([...shown.value,id])]}
    else if(visible.value.length>1){explicitHidden.value=[...explicitHidden.value,id];shown.value=shown.value.filter(key=>key!==id)}
    save()
  }
  function move(id:string,direction:number){const ids=ordered.value.map(column=>column.key),index=ids.indexOf(id),target=index+direction;if(index<0||target<0||target>=ids.length)return;[ids[index],ids[target]]=[ids[target]!,ids[index]!];order.value=ids;save()}
  function reset(){order.value=[];explicitHidden.value=[];shown.value=[];save()}
  return {ordered,visible,hidden,toggle,move,reset}
}
