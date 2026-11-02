import type { ComputedRef, Ref } from "vue"
import { createContext } from "reka-ui"

export const SIDEBAR_COOKIE_NAME = "sidebar_state"
export const SIDEBAR_COOKIE_MAX_AGE = 60 * 60 * 24 * 7
export const SIDEBAR_WIDTH = "16rem"
export const SIDEBAR_WIDTH_MOBILE = "18rem"
export const SIDEBAR_WIDTH_ICON = "3rem"
export const SIDEBAR_KEYBOARD_SHORTCUT = "b"

export const [useSidebar, provideSidebarContext] = createContext<{
  state: ComputedRef<"expanded" | "collapsed">
  open: Ref<boolean>
  setOpen: (value: boolean) => void
  isMobile: Ref<boolean>
  openMobile: Ref<boolean>
  setOpenMobile: (value: boolean) => void
  toggleSidebar: () => void
}>("Sidebar")

/** Local display state only; no authentication/session cookie is created. */
export function readSidebarOpen(name:string):boolean {
 try{return localStorage.getItem(`briareus:sidebar:${name}`)!=="false";}catch{return true;}
}
export function storeSidebarOpen(name:string,open:boolean):void {
 try{localStorage.setItem(`briareus:sidebar:${name}`,String(open));}catch{/* The visible sidebar still updates. */}
}
