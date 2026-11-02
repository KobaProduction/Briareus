/** UI column metadata, independent of the entity and its transport. */
export interface DataTableColumn<Field extends string = string> {
  key:string
  title:string
  dataIndex?:Field
  sortable?:boolean
  defaultHidden?:boolean
}
