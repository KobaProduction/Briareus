import { computed, ref, watch } from "vue";
import type { FilesReadDecode } from "./read-result";
import { buildTextPreview, findTextMatches, pageForMatch, type TextPage } from "./text-window";
export interface FilePreviewContext {
  path?: string;
  content?: string;
  readResult?: FilesReadDecode;
  designPreview?: boolean;
  status?: "empty" | "loading" | "ready" | "denied" | "unavailable";
}
function previewPage(pages: readonly TextPage[], index: number): TextPage {
  const page = pages[index] ?? pages[0];
  if (!page) throw new Error("TEXT_PREVIEW_PAGES_MISSING");
  return page;
}
function decodedStatus(value: FilesReadDecode | null) {
  if (!value) return "loading";
  if (value.kind === "text") return "ready";
  return value.kind === "cancelled" ? "loading" : value.kind;
}
export function useFilePreview(props: FilePreviewContext) {
  const decoded = computed<FilesReadDecode | null>(() => {
    if (props.status !== "ready" || props.readResult === undefined) return null;
    if (!props.path) return { kind: "invalid" };
    const result = props.readResult;
    if ((result.kind === "text" || result.kind === "binary") && result.path !== props.path)
      return { kind: "invalid" };
    return result;
  });
  const effectiveStatus = computed(() => {
    if (props.status !== "ready") return props.status ?? "empty";
    if (props.readResult === undefined)
      return import.meta.env.DEV && props.designPreview && typeof props.content === "string"
        ? "ready"
        : "invalid";
    return decodedStatus(decoded.value);
  });
  const content = computed(() =>
    props.readResult === undefined
      ? import.meta.env.DEV && props.designPreview
        ? props.content
        : undefined
      : decoded.value?.kind === "text"
        ? decoded.value.content
        : undefined,
  );
  const preview = computed(() =>
    buildTextPreview(effectiveStatus.value === "ready" ? (content.value ?? "") : ""),
  );
  const pageIndex = ref(0),
    query = ref(""),
    matchIndex = ref(0);
  const matches = computed(() => findTextMatches(preview.value.text, query.value));
  const page = computed(() => previewPage(preview.value.pages, pageIndex.value));
  const metadata = computed(() =>
    decoded.value?.kind === "text" || decoded.value?.kind === "binary" ? decoded.value : null,
  );
  const highlight = computed(() => {
    const current = page.value,
      text = preview.value.text.slice(current.start, current.end);
    const at = matches.value.positions[matchIndex.value];
    if (at === undefined || at < current.start || at >= current.end)
      return { before: text, match: "", after: "" };
    const relative = at - current.start,
      end = Math.min(text.length, relative + query.value.length);
    return {
      before: text.slice(0, relative),
      match: text.slice(relative, end),
      after: text.slice(end),
    };
  });
  function moveMatch(delta: number): void {
    const count = matches.value.positions.length;
    if (!count) return;
    matchIndex.value = (matchIndex.value + delta + count) % count;
    const position = matches.value.positions[matchIndex.value];
    if (position === undefined) throw new Error("PREVIEW_MATCH_INDEX_INVALID");
    pageIndex.value = pageForMatch(preview.value.pages, position);
  }
  watch(
    () => [props.path, props.status, props.readResult, props.content],
    () => {
      query.value = "";
      pageIndex.value = 0;
      matchIndex.value = 0;
    },
    { flush: "sync" },
  );
  watch(query, () => {
    matchIndex.value = 0;
    pageIndex.value = pageForMatch(preview.value.pages, matches.value.positions[0] ?? 0);
  });

  return {
    effectiveStatus,
    preview,
    pageIndex,
    query,
    matchIndex,
    matches,
    page,
    metadata,
    highlight,
    moveMatch,
  };
}
