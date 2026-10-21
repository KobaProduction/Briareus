/** UI column metadata, independent of the entity and its transport. */
export interface DataTableColumn {
  key:string
  title:string
  dataIndex?:string
  sortable?:boolean
  defaultHidden?:boolean
}
