import { describe, expect, test } from "bun:test"
import {
  imageViewportPoint,
  loadedFrameViewport,
  reconciledAddress,
} from "../src/pages/services/web/playwright/browser-operator-input"

describe("Browser address priority", () => {
  test("user input stays authoritative while focused, including after tab switches", () => {
    expect(reconciledAddress("https://typed.example", "https://old.example", true, false))
      .toBe("https://typed.example")
    expect(reconciledAddress("https://typed.example", "https://other-tab.example", true, false))
      .toBe("https://typed.example")
  })
  test("submitted input survives a blur and intermediate refresh until navigation completes", () => {
    expect(reconciledAddress("https://typed.example", "https://old.example", false, true))
      .toBe("https://typed.example")
    expect(reconciledAddress("https://typed.example", "https://redirect.example", false, false))
      .toBe("https://redirect.example")
  })
  test("a failed or disconnected navigation keeps the draft until an explicit blur", () => {
    expect(reconciledAddress("https://retry.example", "https://old.example", false, true))
      .toBe("https://retry.example")
    expect(reconciledAddress("https://retry.example", "https://old.example", false, false))
      .toBe("https://old.example")
  })
  test("without focus or pending navigation the actual URL is synchronized", () => {
    expect(reconciledAddress("https://draft.example", "https://final.example", false, false))
      .toBe("https://final.example")
  })
})

describe("Browser screencast coordinates", () => {
  const viewport = { w: 1280, h: 720 }
  test("CSS scaling and centered offsets map to the remote CSS viewport", () => {
    const bounds = { left: 180, top: 75, width: 640, height: 360 }
    expect(imageViewportPoint(500, 255, bounds, viewport)).toEqual({ x: 640, y: 360 })
    expect(imageViewportPoint(180, 75, bounds, viewport)).toEqual({ x: 0, y: 0 })
  })
  test("DPR and screenshot pixel size do not alter click coordinates", () => {
    const bounds = { left: 20, top: 40, width: 960, height: 540 }
    expect(imageViewportPoint(740, 445, bounds, viewport)).toEqual({ x: 960, y: 540 })
  })
  test("outside-image and invalid layouts never dispatch remote mouse input", () => {
    const bounds = { left: 180, top: 75, width: 640, height: 360 }
    expect(imageViewportPoint(179, 255, bounds, viewport)).toBeNull()
    expect(imageViewportPoint(500, 437, bounds, viewport)).toBeNull()
    expect(imageViewportPoint(500, 255, { ...bounds, width: 0 }, viewport)).toBeNull()
    expect(imageViewportPoint(NaN, 255, bounds, viewport)).toBeNull()
  })
  test("newly loaded frame dimensions take effect on the next click", () => {
    const bounds = { left: 0, top: 0, width: 320, height: 180 }
    expect(imageViewportPoint(160, 90, bounds, viewport)).toEqual({ x: 640, y: 360 })
    expect(imageViewportPoint(160, 90, bounds, { w: 1920, h: 1080 }))
      .toEqual({ x: 960, y: 540 })
  })
  test("bottom-right edge remains within the CSS viewport", () => {
    const result = imageViewportPoint(320, 180, { left: 0, top: 0, width: 320, height: 180 }, viewport)
    expect(result?.x).toBeLessThan(1280)
    expect(result?.y).toBeLessThan(720)
  })
})


describe("screencast image and metadata pairing", () => {
  const current = { pageId: "chrome-target-1", src: "data:image/jpeg;base64,current", viewport: { w: 1920, h: 1080 } }
  test("the final loaded image exposes its matching CSS viewport size", () => {
    expect(loadedFrameViewport(current, "chrome-target-1", current.src, true))
      .toEqual({ w: 1920, h: 1080 })
  })
  test("older, unready, and other-tab frames never change pointer scale", () => {
    expect(loadedFrameViewport(current, "chrome-target-1", "data:image/jpeg;base64:previous", true)).toBeNull()
    expect(loadedFrameViewport(current, "chrome-target-1", current.src, false)).toBeNull()
    expect(loadedFrameViewport(current, "chrome-target-2", current.src, true)).toBeNull()
    expect(loadedFrameViewport(null, "chrome-target-1", current.src, true)).toBeNull()
  })
})
