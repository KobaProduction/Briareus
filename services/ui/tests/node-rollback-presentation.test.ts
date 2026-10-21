import {expect,test} from 'bun:test'
import {operationError,operationStatus} from '../src/features/nodes/model/operation-presentation'

test('only explicit verified restoration describes the old configuration as restored',()=>{
 const failed={id:'operation',phase:'failed',error:'UPDATE_FAILED',reconciliation_required:false}
 expect(operationStatus(failed).tone).toBe('danger')
 expect(operationError(failed)).not.toContain('восстановлена')
 const restored={...failed,restored:true}
 expect(operationStatus(restored).tone).toBe('warning')
 expect(operationError(restored)).toContain('Обновление не применено')
 expect(operationError(restored)).toContain('Предыдущая конфигурация восстановлена')
 expect(operationStatus({...restored,error:'ROLLBACK_FAILED'}).tone).toBe('danger')
})
