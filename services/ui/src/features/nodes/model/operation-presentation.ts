import type {StatusTone} from '@/shared/ui/status'

export interface FailureDiagnostic {
 stage:'queued'|'pulling'|'stopping'|'creating'|'checking'|'rolling_back'|'unknown'
 component:'worker'|'egress'|'engine'|'controller'
 reason:'process_exited'|'oom'|'readiness_timeout'|'unhealthy'|'helper_unhealthy'|'pull_failed'|'unknown'|'workspace_cleanup_uncertain'|'workspace_initialization_failed'|'workspace_identity_unverified'|'network_policy_cleanup_uncertain'|'network_policy_failed'|'network_policy_unverified'|'engine_unavailable'|'engine_request_rejected'|'rootless_unverified'
 exit_code?:number
 health_exit_code?:number
 health_status?:'starting'|'healthy'|'unhealthy'|'none'
 oom_killed?:boolean
}
export interface PlacementOperation {id:string;phase:string;error:string|null;reconciliation_required:boolean;restored?:boolean;updated_at?:string;diagnostic?:FailureDiagnostic|null}
export interface OperationStatus {label:string;tone:StatusTone}
const phases:Record<string,OperationStatus>={
 queued:{label:'В очереди',tone:'warning'},
 pulling:{label:'Загрузка образа',tone:'info'},
 stopping:{label:'Остановка контейнера',tone:'warning'},
 creating:{label:'Создание контейнера',tone:'info'},
 checking:{label:'Проверка готовности',tone:'info'},
 rolling_back:{label:'Восстановление сборки',tone:'warning'},
 succeeded:{label:'Выполнено',tone:'success'},
 failed:{label:'Ошибка операции',tone:'danger'},
}
const activePhases=new Set(['queued','pulling','stopping','creating','checking','rolling_back'])
export function operationInProgress(operation:PlacementOperation|null){
 return !!operation&&!operation.reconciliation_required&&activePhases.has(operation.phase)
}
export function operationStatus(operation:PlacementOperation|null):OperationStatus{
 if(!operation)return {label:'Нет операций',tone:'neutral'}
 if(operation.reconciliation_required)return {label:'Требуется сверка',tone:'warning'}
 if(operation.restored&&operation.phase==='failed'&&operation.error==='UPDATE_FAILED')return {label:'Предыдущая конфигурация',tone:'warning'}
 return phases[operation.phase]??{label:'Статус неизвестен',tone:'neutral'}
}
export function placementStatus(value:string,sequence=1):OperationStatus{
 const states:Record<string,OperationStatus>={pending:{label:'В очереди',tone:'warning'},updating:{label:sequence>1?'Обновляется':'Запускается',tone:'info'},ready:{label:'Работает',tone:'success'},failed:{label:'Ошибка',tone:'danger'},disabled:{label:'Отключён',tone:'neutral'}}
 return states[value]??{label:'Статус неизвестен',tone:'neutral'}
}
export function operationError(operation:PlacementOperation|null){
 if(!operation?.error&&operation?.phase!=='failed')return ''
 if(operation?.restored&&operation.phase==='failed'&&operation.error==='UPDATE_FAILED')return 'Обновление не применено. Предыдущая конфигурация восстановлена.'
 const messages:Record<string,string>={
  UPDATE_FAILED:'Не удалось запустить или обновить MCP.',
  ROLLBACK_FAILED:'Не удалось восстановить предыдущую сборку.',
  CONTROLLER_INTERRUPTED:'Операция прервана до подтверждения результата.',
  UNMANAGED_INSTANCE:'Не удалось подтвердить управление контейнером.',
 }
 return messages[operation?.error??'']??'Операция завершилась с ошибкой.'
}

/** Only finite typed facts from the server; never guess from UPDATE_FAILED. */
export function diagnosticCause(diagnostic:FailureDiagnostic|null|undefined){
 const reasons:Record<string,string>={
  process_exited:'Процесс компонента завершился.',
  oom:'Контейнер остановлен из-за нехватки памяти.',
  readiness_timeout:'Компонент не подтвердил готовность за отведённое время.',
  unhealthy:'Проверка работоспособности контейнера завершилась ошибкой.',
  helper_unhealthy:'Служебный компонент не подтвердил работоспособность.',
  pull_failed:'Не удалось загрузить образ контейнера.',
  workspace_cleanup_uncertain:'Не удалось подтвердить удаление служебного контейнера рабочей папки.',
  workspace_initialization_failed:'Не удалось подготовить рабочую папку проекта.',
  workspace_identity_unverified:'Не удалось подтвердить принадлежность рабочей папки проекту.',
  network_policy_cleanup_uncertain:'Не удалось подтвердить удаление служебного сетевого контейнера.',
  network_policy_failed:'Не удалось применить сетевые ограничения контейнера.',
  network_policy_unverified:'Не удалось подтвердить сетевые ограничения контейнера.',
  engine_unavailable:'Движок контейнеров не ответил.',
  engine_request_rejected:'Движок контейнеров отклонил операцию.',
  rootless_unverified:'Не удалось подтвердить изолированный режим запуска.',
 }
 return reasons[diagnostic?.reason??'']??'Подробная причина не передана сервером.'
}
export function diagnosticFacts(diagnostic:FailureDiagnostic|null|undefined){
 if(!diagnostic)return []
 const facts:{label:string;value:string}[]=[]
 const component:Record<string,string>={worker:'Контейнер MCP',egress:'Сетевой компонент',engine:'Движок контейнеров',controller:'Управление операцией'}
 const health:Record<string,string>={starting:'Запускается',healthy:'Работоспособен',unhealthy:'Ошибка проверки',none:'Проверка не настроена'}
 if(component[diagnostic.component])facts.push({label:'Компонент',value:component[diagnostic.component]!})
 if(phases[diagnostic.stage])facts.push({label:'Этап ошибки',value:phases[diagnostic.stage]!.label})
 if(typeof diagnostic.exit_code==='number'&&Number.isInteger(diagnostic.exit_code)&&diagnostic.exit_code>=0&&diagnostic.exit_code<=255)facts.push({label:'Код завершения',value:String(diagnostic.exit_code)})
 if(typeof diagnostic.health_exit_code==='number'&&Number.isInteger(diagnostic.health_exit_code)&&diagnostic.health_exit_code>=-1&&diagnostic.health_exit_code<=255)facts.push({label:'Код проверки работоспособности',value:String(diagnostic.health_exit_code)})
 if(diagnostic.health_status&&health[diagnostic.health_status])facts.push({label:'Работоспособность',value:health[diagnostic.health_status]!})
 if(typeof diagnostic.oom_killed==='boolean')facts.push({label:'Остановка контейнера по OOM',value:diagnostic.oom_killed?'Да':'Нет'})
 return facts
}
