import {describe,expect,it} from "bun:test"
import type {VerifiedPlatformContext} from "../src/entities/workspace"
import {areaProjects,projectGroups,scopedContext} from "../src/features/workspace-scope/model/scope"

const context:VerifiedPlatformContext={
  authenticated:true,authority:"platform",rauthy:{issuer:"https://identity.example",subject:"viewer"},
  user:{id:"viewer",role:"user",enabled:true},expires_at:"2030-01-01T00:00:00Z",
  teams:[{id:"alpha",name:"Alpha",owner:false},{id:"beta",name:"Beta",owner:false}],
  projects:[
    {id:"alpha-one",name:"Alpha One",owner:{kind:"team",id:"alpha"},permissions:["use_resources"]},
    {id:"alpha-two",name:"Alpha Two",owner:{kind:"team",id:"alpha"},permissions:[]},
    {id:"beta-one",name:"Beta One",owner:{kind:"team",id:"beta"},permissions:["use_resources"]},
    {id:"personal",name:"Personal",owner:{kind:"user",id:"viewer"},permissions:["use_resources"]},
  ],
}

describe("workspace areas from verified membership",()=>{
  it("separates administrator-wide visibility from the administrator's own work",()=>{
    const foreign={id:'foreign',name:'Other team project',owner:{kind:'team' as const,id:'foreign-team'},permissions:[]}
    const otherPersonal={id:'other-personal',owner:{kind:'user' as const,id:'other-user'},permissions:[]}
    const admin:VerifiedPlatformContext={...context,user:{...context.user,role:'operator'},teams:[...context.teams,{id:'foreign-team',name:'Other team',owner:false,member:false}],projects:[...context.projects,foreign,otherPersonal]}
    expect(areaProjects(admin,{kind:'all'})).toEqual(context.projects)
    expect(areaProjects(admin,{kind:'admin'})).toEqual(admin.projects)
    expect(areaProjects(admin,{kind:'personal'}).map(project=>project.id)).toEqual(['personal'])
    expect(areaProjects({...admin,user:{...context.user,role:'user'}},{kind:'admin'})).toEqual([])
  })
  it("separates team projects and the signed-in user's personal projects",()=>{
    expect(areaProjects(context,{kind:"team",id:"alpha"}).map(project=>project.id)).toEqual(["alpha-one","alpha-two"])
    expect(areaProjects(context,{kind:"personal"}).map(project=>project.id)).toEqual(["personal"])
    expect(areaProjects(context,{kind:"all"})).toEqual(context.projects)
  })
  it("does not make an absent team's projects available to a user or an operator",()=>{
    for(const role of ["user","operator"] as const){
      const viewer={...context,user:{...context.user,role}}
      expect(areaProjects(viewer,{kind:"team",id:"absent"})).toEqual([])
      expect(scopedContext(viewer,{kind:"all"},"absent").projects).toEqual([])
    }
  })
  it("cannot resurrect a selected project from outside the selected team",()=>{
    expect(scopedContext(context,{kind:"team",id:"alpha"},"beta-one").projects).toEqual([])
    expect(scopedContext(context,{kind:"personal"},"alpha-one").projects).toEqual([])
  })
  it("groups aggregate lists by owner and retains only the selected project in focused view",()=>{
    expect(projectGroups(context,{kind:"all"},null).map(group=>[group.name,group.projects.map(project=>project.id)]))
      .toEqual([["Alpha",["alpha-one","alpha-two"]],["Beta",["beta-one"]],["Личные проекты",["personal"]]])
    expect(projectGroups(context,{kind:"team",id:"alpha"},"alpha-two").flatMap(group=>group.projects.map(project=>project.id)))
      .toEqual(["alpha-two"])
  })
  it("preserves permissions, identity and original membership while changing presentation",()=>{
    const before=JSON.stringify(context)
    const focused=scopedContext(context,{kind:"team",id:"alpha"},"alpha-two")
    expect(focused.projects[0]?.permissions).toEqual([])
    expect(focused.user).toBe(context.user)
    expect(focused.rauthy).toBe(context.rauthy)
    expect(focused.expires_at).toBe(context.expires_at)
    expect(focused.teams.map(team=>team.id)).toEqual(["alpha"])
    expect(JSON.stringify(context)).toBe(before)
  })
})
