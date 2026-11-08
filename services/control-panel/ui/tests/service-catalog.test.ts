import { describe, expect, test } from "bun:test"
import {
  groupedServices,
  serviceConnectionUrl,
  serviceForRoute,
  servicePath,
} from "../src/shared/services/catalog"
import type { McpServiceDescriptor } from "../src/shared/services/types"
const services: McpServiceDescriptor[] = [
  {
    id: "github",
    name: "GitHub",
    group: "svc",
    connected: true,
    mcp_path: "/github/mcp",
  },
  {
    id: "gitlab",
    name: "GitLab",
    group: "svc",
    connected: false,
    mcp_path: "/gitlab/mcp",
  },
  {
    id: "coolify",
    name: "Coolify",
    group: "infrastructure",
    connected: false,
    mcp_path: "/coolify/mcp",
  },
  {
    id: "future-provider",
    name: "Future provider",
    group: "custom",
    connected: true,
    mcp_path: "/future/mcp",
  },
]
describe("discovered MCP catalog", () => {
  test("only connected providers and non-empty groups are shown by default; reveal retains disconnected status", () => {
    expect(
      groupedServices(services, false).map((group) => [
        group.id,
        group.services.map((service) => service.id),
      ]),
    ).toEqual([
      ["svc", ["github"]],
      ["custom", ["future-provider"]],
    ])
    const revealed = groupedServices(services, true)
    expect(
      revealed
        .flatMap((group) => group.services)
        .find((service) => service.id === "gitlab")?.connected,
    ).toBe(false)
    expect(revealed.some((group) => group.id === "infrastructure")).toBe(true)
    expect(groupedServices([], true)).toEqual([])
  })
  test("future providers remain addressable and Server retains Files and Terminal under one MCP", () => {
    expect(servicePath("future-provider")).toBe("services/future-provider")
    expect(serviceForRoute(servicePath("future-provider"))).toBe(
      "future-provider",
    )
    expect(serviceForRoute("server/files")).toBe("server")
    expect(serviceForRoute("server/terminal")).toBe("server")
    expect(serviceForRoute("services/playwright")).toBe("playwright")
    expect(serviceForRoute("settings/interface")).toBeNull()
  })
  test("connection URLs cannot redirect users to a foreign host or attach token parameters", () => {
    expect(
      serviceConnectionUrl("/playwright/mcp", "https://node.example"),
    ).toBe("https://node.example/playwright/mcp")
    for (const path of [
      "//other.example/mcp",
      "https://other.example/mcp",
      "/mcp?token=secret",
      "/mcp#fragment",
      "/\\other.example",
    ])
      expect(serviceConnectionUrl(path, "https://node.example")).toBeNull()
  })
})
