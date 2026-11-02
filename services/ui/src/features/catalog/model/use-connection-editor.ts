import { computed, onBeforeUnmount, ref, watch } from "vue"
import { connectionConfiguration, connectionDraftDirty, copyConnectionDraft, newConnectionDraft,
  type ConnectionDraft, type ConnectionProvider } from "./connection-draft"
import { validConnectionDraft } from "./connection-validation"
import type { ConnectionSubmit } from "./connection-contracts"

interface ConnectionEditor {
  provider: ConnectionProvider
  initial?: Partial<ConnectionDraft>
  busy: () => boolean
  submit: ConnectionSubmit
  saved: () => void
  close: () => void
}
export function useConnectionEditor(editor: ConnectionEditor) {
  // The baseline never contains credential bytes; comparison only records presence.
  const baseline = { ...newConnectionDraft(editor.provider), ...editor.initial, provider: editor.provider, credential: "" }
  const draft = ref<ConnectionDraft>(copyConnectionDraft(baseline))
  const verified = ref(false), discard = ref(false)
  let generation = 0, verifiedRevision = -1, disposed = false
  const dirty = computed(() => connectionDraftDirty(draft.value, baseline))
  const valid = computed(() => validConnectionDraft(draft.value, Boolean(editor.initial)))
  watch(draft, () => { ++generation; verified.value = false; verifiedRevision = -1 }, { deep: true, flush: "sync" })
  watch(() => draft.value.auth_type, () => { draft.value.credential = "" }, { flush: "sync" })
  async function verify(): Promise<void> {
    if (disposed || editor.busy() || !valid.value) return
    const run = generation
    const result = await editor.submit("verify", connectionConfiguration(draft.value), draft.value.credential)
    if (disposed || run !== generation) return
    if (result && "status" in result && result.status === "connected") { verifiedRevision = run; verified.value = true }
  }
  async function save(): Promise<void> {
    if (disposed || editor.busy() || !valid.value || !verified.value || verifiedRevision !== generation) return
    const run = generation
    const result = await editor.submit("create", connectionConfiguration(draft.value), draft.value.credential)
    if (disposed || run !== generation) return
    if (result && "item" in result) { draft.value.credential = ""; editor.saved() }
  }
  function close(): void {
    if (editor.busy()) return
    if (dirty.value) discard.value = true
    else editor.close()
  }
  onBeforeUnmount(() => { disposed = true; ++generation; draft.value.credential = ""; draft.value.ca_cert_pem = "" })
  return { draft, verified, discard, dirty, valid, verify, save, close }
}
