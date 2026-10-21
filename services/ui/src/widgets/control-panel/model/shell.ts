import type {PlatformPageId} from "@/features/platform/types"
export interface ShellProps {
  page:PlatformPageId
  heading:string
  authenticated:boolean
  sessionActive?:boolean
  busy?:boolean
  designPreview?:boolean
  presentationOnly?:boolean
  presentationPages?:readonly PlatformPageId[]
  accountName?:string|null
  accountEmail?:string|null
  scopeName?:string
}
