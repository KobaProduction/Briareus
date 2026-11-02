import { afterEach, describe, expect, it } from "bun:test";
import {
  finishPasswordSetup,
  preparePasswordSetup,
  recoverPasswordSetup,
} from "../src/features/platform/api/password-setup";
import { passwordSetupPolicy } from "../src/features/platform/model/password-setup";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});
const user = "A".repeat(24),
  code = "B".repeat(64);
describe("provider-owned password setup boundary", () => {
  it("prepares only the same-origin BFF using the provider reset code", async () => {
    const requests: { url: string; init: RequestInit | undefined }[] = [];
    globalThis.fetch = Object.assign(
      async (url: RequestInfo | URL, init?: RequestInit) => {
        requests.push({ url: String(url), init });
        return Response.json({
          prepared: true,
          password_policy: { length_min: 12, length_max: 128, include_digits: null },
        });
      },
      { preconnect: originalFetch.preconnect },
    );
    expect(
      await preparePasswordSetup(
        `https://provider.invalid/auth/v1/users/${user}/reset/${code}`,
        new AbortController().signal,
      ),
    ).toEqual({ length_min: 12, length_max: 128 });
    expect(requests.map((request) => request.url)).toEqual(["/api/v1/auth/password-setup/prepare"]);
    expect(requests[0]?.init?.credentials).toBe("same-origin");
    expect(JSON.parse(String(requests[0]?.init?.body))).toEqual({ user_id: user, code });
  });
  it("rejects malformed policy or code without inventing valid setup state", async () => {
    expect(() => passwordSetupPolicy({ length_min: "12" })).toThrow("SETUP_POLICY_INVALID");
    let calls = 0;
    globalThis.fetch = Object.assign(
      async () => {
        calls++;
        return Response.json({});
      },
      { preconnect: originalFetch.preconnect },
    );
    await expect(
      preparePasswordSetup("not a provider code", new AbortController().signal),
    ).rejects.toThrow("SETUP_CODE_INVALID_OR_EXPIRED");
    expect(calls).toBe(0);
  });
  it("does not accept a provider refusal or malformed recovery challenge", async () => {
    globalThis.fetch = Object.assign(
      async () => Response.json({ error: { code: "SETUP_PROVIDER_REJECTED" } }, { status: 403 }),
      { preconnect: originalFetch.preconnect },
    );
    await expect(
      finishPasswordSetup("test-password", new AbortController().signal),
    ).rejects.toThrow("SETUP_PROVIDER_REJECTED");
    globalThis.fetch = Object.assign(async () => Response.json({ challenge: 4 }), {
      preconnect: originalFetch.preconnect,
    });
    await expect(
      recoverPasswordSetup("operator@example.invalid", new AbortController().signal),
    ).rejects.toThrow("SETUP_PROVIDER_UNAVAILABLE");
  });
});
