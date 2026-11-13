/** Keep a user's address draft authoritative while it is being edited or submitted. */
export function reconciledAddress(
  draft: string,
  remoteUrl: string,
  focused: boolean,
  navigating: boolean,
): string {
  return focused || navigating ? draft : remoteUrl
}

export interface BrowserImageBounds {
  left: number
  top: number
  width: number
  height: number
}

export interface BrowserImageViewport {
  w: number
  h: number
}

/** Convert a click on the rendered screencast to CSS viewport coordinates. */
export function imageViewportPoint(
  clientX: number,
  clientY: number,
  bounds: BrowserImageBounds,
  viewport: BrowserImageViewport,
): { x: number; y: number } | null {
  if (
    ![clientX, clientY, bounds.left, bounds.top, bounds.width, bounds.height,
      viewport.w, viewport.h].every(Number.isFinite) ||
    bounds.width <= 0 || bounds.height <= 0 || viewport.w <= 0 || viewport.h <= 0
  ) return null
  const x = (clientX - bounds.left) / bounds.width
  const y = (clientY - bounds.top) / bounds.height
  if (x < 0 || x > 1 || y < 0 || y > 1) return null
  // A click on the far edge remains inside the remote viewport.
  return {
    x: Math.min(x * viewport.w, viewport.w - Number.EPSILON * viewport.w),
    y: Math.min(y * viewport.h, viewport.h - Number.EPSILON * viewport.h),
  }
}

/** Only pair coordinates with the image that actually finished decoding. */
export function loadedFrameViewport(
  pending: { pageId: string; src: string; viewport: BrowserImageViewport } | null,
  selectedPageId: string,
  displayedSrc: string,
  loaded: boolean,
): BrowserImageViewport | null {
  if (!loaded || !pending || pending.pageId !== selectedPageId || pending.src !== displayedSrc)
    return null
  return pending.viewport
}

/** A page-navigation failure is browser-local, not a panel or transport failure. */
export function browserErrorSurface(
  requestId: string | undefined,
  pendingNavigationRequestId: string | null,
): "navigation" | "browser" {
  return requestId && requestId === pendingNavigationRequestId ? "navigation" : "browser"
}

export function browserErrorSummary(message: string): string {
  return message.split(/\nCall log:/u, 1)[0]?.trim() ?? ""
}

/** Chromium displays its own navigation failure page; do not duplicate it in the panel. */
export function browserOperatorShouldShowDialog(detail: string, navigation: boolean): boolean {
  return !navigation || !/\bnet::ERR_[A-Z_]+\b/u.test(detail)
}
