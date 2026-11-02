<script setup lang="ts">
import {computed,ref} from "vue"
import {Button} from "@/shared/ui/button"
import {PasswordSetup} from "@/features/platform"
import type {RauthyPanelState} from "@/entities/identity"
import {RauthySignIn} from "@/features/platform"

/** One honest browser login state. No speculative Init/Cancel button,
 * inactive credential placeholders, provider details or hosted login link.
 * Rauthy and Platform proof remain exclusively owned by Backend/parent.
 */
const props=withDefaults(defineProps<{
  designPreview?:boolean
  initialSession?:RauthyPanelState|null
  managedLogout?:boolean
}>(),{designPreview:false})
const emit=defineEmits<{
  providerState:[value:RauthyPanelState|{kind:"checking"}]
  logoutRequested:[]
}>()
const initialState=computed<RauthyPanelState|null>(()=>
  props.designPreview?{kind:"signed_out"}:props.initialSession??null)
const mode=ref<"login"|"invitation"|"recovery">("login")
</script>

<template>
  <div class="mx-auto w-full max-w-lg py-6 sm:py-12">
    <PasswordSetup v-if="mode!=='login'" :key="mode" :mode="mode" @back="mode='login'"/>
    <RauthySignIn v-else :initial-state="initialState" :managed-logout="managedLogout"
      @logout-requested="emit('logoutRequested')"
      @state="emit('providerState',$event)"/>
    <div v-if="mode==='login'&&initialState?.kind==='signed_out'" class="mt-4 flex justify-center gap-2">
      <Button variant="link" @click="mode='recovery'">Забыли пароль?</Button>
      <Button variant="link" @click="mode='invitation'">У меня есть приглашение</Button>
    </div>
  </div>
</template>
