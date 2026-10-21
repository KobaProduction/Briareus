import {describe,it,expect} from 'bun:test'
import {presentPermissions,shortIdentifier} from '../src/entities/permission/model/presentation'

describe('permission presentation keeps module boundaries',()=>{
  it('distinguishes the actual Hand for a shared operation',()=>{
    const groups=presentPermissions(['integrations.use'],[
      {hand:'svc',action:'integrations.use',tool:'repository_read',resource:{kind:'repository',id:'repo'}},
      {hand:'infrastructure',action:'integrations.use',tool:'logs_read',resource:{kind:'application',id:'app'}},
    ])
    expect(groups.map(group=>group.id)).toEqual(['svc','infrastructure'])
    expect(groups[0]!.tools).toEqual(['repository_read'])
    expect(groups[1]!.tools).toEqual(['logs_read'])
  })
  it('does not claim a concrete Hand when an operation has ambiguous ownership',()=>{
    expect(presentPermissions(['integrations.use'],[]).map(group=>group.id)).toEqual(['integrations'])
  })
  it('separates system metadata without dropping the owner evidence',()=>{
    const groups=presentPermissions(['files.read','files.write','project.metadata.read'],[])
    expect(groups[0]!.actions).toEqual(['Чтение','Запись'])
    expect(groups.find(group=>group.system)?.operations).toEqual(['project.metadata.read'])
  })
  it('keeps both ends of an identifier',()=>{
    expect(shortIdentifier('11111111-2222-4333-8444-555555555555')).toBe('11111111…555555')
  })
})
