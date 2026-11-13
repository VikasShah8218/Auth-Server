import { describe, expect, it } from "vitest";

import { DEFAULT_RETURN_TO, safeReturnTo } from "./returnTo";

const ORIGIN = "https://auth.example.com";
const ok = "/oauth/authorize?response_type=code&client_id=anpr-web&state=x";

describe("safeReturnTo", () => {
  it("keeps a same-origin authorize path with its query", () => {
    expect(safeReturnTo(ok, ORIGIN)).toBe(ok);
  });

  it.each([
    ["missing", undefined],
    ["empty", ""],
    ["absolute URL elsewhere", "https://evil.example/oauth/authorize?x=1"],
    ["absolute URL on this origin", `${ORIGIN}/oauth/authorize?x=1`],
    ["protocol-relative", "//evil.example/oauth/authorize?x=1"],
    ["javascript", "javascript:alert(1)"],
    ["other path", "/v1/admin/users"],
    ["path traversal", "/oauth/authorize/../../v1/admin?x=1"],
    ["backslash trick", "/oauth/authorize?x=1\\@evil.example"],
    ["prefix lookalike", "/oauth/authorizeX?x=1"],
    ["encoded slashes", "/%2F%2Fevil.example"],
    ["whitespace", "/oauth/authorize?x=1 https://evil.example"],
  ])("refuses %s", (_, value) => {
    expect(safeReturnTo(value, ORIGIN)).toBe(DEFAULT_RETURN_TO);
  });
});
