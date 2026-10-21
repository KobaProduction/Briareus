/** Presentation rows; callbacks retain the owning feature's authority checks. */
export interface ActivityRow {
  id:string
  projectId:string
  name:string
  actor:string
  operations:string
  status:string
  expires:string
  expiresAt?:string
  description?:string|null
  created?:string|null
  statusCode?:string
  sessionId?:string
  permissions?:{id:string;title:string;actions:string[];operations:string[];tools:string[];system:boolean}[]
  inspect?:()=>void
  actions:{label:string;run:()=>void;disabled?:boolean}[]
}
export interface ActivitySnapshot {rows:ActivityRow[];loading:boolean;message:string}
