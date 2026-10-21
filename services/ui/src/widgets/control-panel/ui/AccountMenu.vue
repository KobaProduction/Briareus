<script setup lang="ts">
import {computed,ref} from "vue"
import {ChevronDown,LogOut,Settings,UserRound} from "lucide-vue-next"
import {Button} from "@/shared/ui/button"
import {Popover,PopoverTrigger,PopoverContent} from "@/shared/ui/popover"
import {Separator} from "@/shared/ui/separator"
const props=defineProps<{name?:string|null;email?:string|null;busy?:boolean}>()
const emit=defineEmits<{logout:[]}>()
const open=ref(false)
const initial=computed(()=>(props.name||props.email||'П').trim().slice(0,1).toLocaleUpperCase())
function navigate(page:string){open.value=false;location.hash='platform/'+page}
</script>
<template>
  <Popover v-model:open="open"><PopoverTrigger as-child><Button variant="outline" size="sm" class="h-7 gap-1 border-transparent bg-transparent px-1" aria-label="Меню аккаунта"><span class="grid size-5 shrink-0 place-items-center rounded-full border border-border bg-zinc-700 text-[10px] font-semibold text-white ring-1 ring-white/10">{{initial}}</span><ChevronDown class="size-3 text-muted-foreground"/></Button></PopoverTrigger><PopoverContent align="end" class="w-64 p-1.5"><div class="min-w-0 px-2 py-2"><p class="truncate text-sm font-medium">{{name||'Мой аккаунт'}}</p><p class="truncate text-xs text-muted-foreground">{{email}}</p></div><Separator class="my-1"/><Button variant="ghost" class="w-full justify-start gap-2" @click="navigate('profile')"><UserRound class="size-4"/>Профиль</Button><Button variant="ghost" class="w-full justify-start gap-2" @click="navigate('settings')"><Settings class="size-4"/>Настройки</Button><Separator class="my-1"/><Button variant="ghost" class="w-full justify-start gap-2 text-muted-foreground" :disabled="busy" @click="open=false;emit('logout')"><LogOut class="size-4"/>Выйти</Button></PopoverContent></Popover>
</template>
