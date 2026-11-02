import { onScopeDispose, watch } from "vue";

/** A UI request may finish after its owner changes. This epoch only fences
 * presentation updates; the server still validates every command and version. */
export function useNodeScope(owner: () => string, onChange: () => void) {
  let revision = 0,
    disposed = false;
  watch(
    owner,
    () => {
      revision++;
      onChange();
    },
    { flush: "sync" },
  );
  onScopeDispose(() => {
    revision++;
    disposed = true;
  });
  return { capture: () => revision, current: (run: number) => !disposed && run === revision };
}
