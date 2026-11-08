"""Read an explicit operator selection without reading or persisting OS clipboards."""
from __future__ import annotations

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

SELECTION_SCRIPT = """() => {
  if (!document.hasFocus()) return '';
  let active = document.activeElement;
  while (active?.shadowRoot?.activeElement) active = active.shadowRoot.activeElement;
  if (active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement) {
    if (active.type === 'password') return '';
    const start = active.selectionStart, end = active.selectionEnd;
    return start !== null && end !== null ? active.value.slice(start, end) : '';
  }
  const selection = active?.getRootNode?.().getSelection?.() ?? window.getSelection();
  return selection?.toString() ?? '';
}"""

async def read_selection(page: Page) -> str:
    for frame in page.frames:
        if frame.is_detached():
            continue
        try:
            text: object = await frame.evaluate(SELECTION_SCRIPT)
        except PlaywrightError:
            continue
        if isinstance(text, str) and text:
            if len(text) > 100_000:
                raise ValueError("clipboard selection is too large")
            return text
    return ""
