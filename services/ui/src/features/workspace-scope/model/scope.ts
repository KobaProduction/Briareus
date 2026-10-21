import type {VerifiedPlatformContext,PlatformProjectProof} from "@/entities/workspace/model/proof"

/** Presentation scope only. Every command still needs current owner authority. */
export type WorkspaceArea={kind:'all'}|{kind:'personal'}|{kind:'admin'}|{kind:'team';id:string}
export interface ProjectGroup {id:string;name:string;projects:PlatformProjectProof[]}
export function areaProjects(context:VerifiedPlatformContext,area:WorkspaceArea):PlatformProjectProof[]{
  if(area.kind==='admin')return context.user.role==='operator'?context.projects:[]
  const memberTeams=new Set(context.teams.filter(team=>team.member!==false).map(team=>team.id))
  return context.projects.filter(project=>area.kind==='all'?(project.owner.kind==='user'?project.owner.id===context.user.id:memberTeams.has(project.owner.id)):(area.kind==='personal'
    ?project.owner.kind==='user'&&project.owner.id===context.user.id
    :project.owner.kind==='team'&&project.owner.id===area.id))
}
export function areaName(context:VerifiedPlatformContext,area:WorkspaceArea):string {
  return area.kind==='admin'?'Администрирование':area.kind==='all'?'Все команды':area.kind==='personal'?'Личные проекты':context.teams.find(team=>team.id===area.id)?.name||'Команда'
}
export function projectGroups(context:VerifiedPlatformContext,area:WorkspaceArea,projectId:string|null):ProjectGroup[]{
  const projects=areaProjects(context,area).filter(project=>!projectId||project.id===projectId)
  const groups=new Map<string,ProjectGroup>()
  for(const project of projects){
    const id=project.owner.kind+':'+project.owner.id
    const name=project.owner.kind==='user'?'Личные проекты':context.teams.find(team=>team.id===project.owner.id)?.name||'Команда'
    if(!groups.has(id))groups.set(id,{id,name,projects:[]})
    groups.get(id)!.projects.push(project)
  }
  return [...groups.values()]
}
export function scopedContext(context:VerifiedPlatformContext,area:WorkspaceArea,projectId:string|null):VerifiedPlatformContext {
  const projects=areaProjects(context,area).filter(project=>!projectId||project.id===projectId)
  const teamIds=new Set(projects.filter(project=>project.owner.kind==='team').map(project=>project.owner.id))
  if(area.kind==='team')teamIds.add(area.id)
  return {...context,projects,teams:context.teams.filter(team=>area.kind==='admin'?context.user.role==='operator':area.kind==='all'?team.member!==false:teamIds.has(team.id))}
}
