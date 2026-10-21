import {defineAsyncComponent,defineComponent,h,type Component} from "vue"
import ProtectedSectionLoadState from "@/shared/ui/ProtectedSectionLoadState.vue"
const ProtectedSectionLoadError=defineComponent({
  name:"ProtectedSectionLoadError",
  setup:()=>()=>h(ProtectedSectionLoadState,{failed:true}),
})
export function protectedPage(loader:()=>Promise<{default:Component}>){
  return defineAsyncComponent({
    loader,
    delay:200,
    timeout:12000,
    loadingComponent:ProtectedSectionLoadState,
    errorComponent:ProtectedSectionLoadError,
  })
}
