import type {ModuleId} from './catalog'
/** Navigation taxonomy; availability is supplied independently by the service. */
export const moduleGroups:{id:string;name:string;module?:ModuleId;children?:{id:ModuleId;name:string;planned?:boolean}[]}[]=[
  {id:'files',name:'Файлы',module:'files'},
  {id:'terminal',name:'Терминал',module:'terminal'},
  {id:'development',name:'Разработка',module:'serena',children:[{id:'serena',name:'Serena · LSP'}]},
  {id:'web',name:'Web',module:'web',children:[{id:'web',name:'Chromium ноды'},{id:'browser-external',name:'Внешний браузер агента'}]},
  {id:'svc',name:'Системы контроля версий',module:'svc',children:[{id:'github',name:'GitHub'},{id:'gitlab',name:'GitLab'}]},
  {id:'infrastructure',name:'Инфраструктура',module:'infrastructure',children:[{id:'signoz',name:'SigNoz'},{id:'coolify',name:'Coolify'},{id:'grafana',name:'Grafana',planned:true}]},
  {id:'analysis',name:'Анализ',module:'analysis'},
]
