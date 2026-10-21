import {describe,expect,test} from 'bun:test'
import {currentPlacementRelease,placementConfigurationField,placementHasChanges} from '../src/features/nodes/model/placement-edit'
import {defaultConfiguration} from '../src/features/nodes/model/module-configuration'

const releases=[{id:'old',image:'registry/module@sha256:old'},{id:'current',image:'registry/module@sha256:current'},{id:'alias',image:'registry/module@sha256:current'}]
const limits={memory_bytes:1024**3,cpu_millis:500,pids:128}
const placement={module:'web',state:'ready',release_uuid:'current',limits,configuration:null,project_workspace:{id:'owned-project-workspace',read_only:false}}

describe('editing a running MCP placement',()=>{
 test('opening keeps the actual release despite older or newer catalogue entries',()=>{
  expect(currentPlacementRelease('current',releases)).toBe('current')
  expect(currentPlacementRelease('missing',releases)).toBe('')
 })
 test('unchanged image, default configuration and workspace never request a restart',()=>{
  expect(placementHasChanges(placement,'current',releases,{...limits},defaultConfiguration('web'),{...placement.project_workspace})).toBe(false)
  expect(placementHasChanges(placement,'alias',releases,limits,defaultConfiguration('web'),placement.project_workspace)).toBe(false)
  expect(placementConfigurationField('web',null,defaultConfiguration('web'))).toEqual({})
  expect(placementConfigurationField('serena',null,defaultConfiguration('serena'))).toEqual({})
 })
 test('an intentional release, limit, workspace mode or detach is a real change',()=>{
  const defaults=defaultConfiguration('web')
  expect(placementHasChanges(placement,'old',releases,limits,defaults,placement.project_workspace)).toBe(true)
  expect(placementHasChanges(placement,'current',releases,{...limits,cpu_millis:750},defaults,placement.project_workspace)).toBe(true)
  expect(placementHasChanges(placement,'current',releases,limits,defaults,{...placement.project_workspace,read_only:true})).toBe(true)
  expect(placementHasChanges(placement,'current',releases,limits,defaults,null)).toBe(true)
 })
 test('configuration edits are transmitted but a limit-only edit preserves null/default wire values',()=>{
  const browser=defaultConfiguration('web')
  browser.browser!.developer_access_enabled=true
  expect(placementConfigurationField('web',null,browser)).toEqual({configuration:browser})
  const existing={browser:{...browser.browser!}}
  expect(placementConfigurationField('web',existing,{browser:{...existing.browser}})).toEqual({})
  expect(placementHasChanges(placement,'current',releases,limits,browser,placement.project_workspace)).toBe(true)
 })
 test('same-content recovery of a failed placement remains available',()=>{
  expect(placementHasChanges({...placement,state:'failed'},'current',releases,limits,defaultConfiguration('web'),placement.project_workspace)).toBe(true)
 })
})
