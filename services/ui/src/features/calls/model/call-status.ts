import type {StatusTone} from '@/shared/ui/status'

const states:Record<string,{label:string;tone:StatusTone}>={
 completed:{label:'Выполнено',tone:'success'},
 failed:{label:'Ошибка',tone:'danger'},
 unknown:{label:'Результат не подтверждён',tone:'warning'},
 running:{label:'Выполняется',tone:'info'},
 accepted:{label:'Принято',tone:'info'},
 cancelled:{label:'Отменено',tone:'neutral'},
}
export function callStatus(value:string):{label:string;tone:StatusTone}{
 return states[value]??{label:value,tone:'neutral'}
}
