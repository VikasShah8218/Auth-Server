import { describe, expect, it } from "vitest";

import { validateLoginSearch, validateUsersSearch } from "./search";

describe("validateLoginSearch", () => {
  it("keeps a long return_to whole (the PKCE challenge is near the end)", () => {
    const returnTo = `/oauth/authorize?response_type=code&client_id=auth-console&state=${"s".repeat(40)}&code_challenge=${"c".repeat(43)}&code_challenge_method=S256&redirect_uri=${"r".repeat(120)}`;
    expect(returnTo.length).toBeGreaterThan(200);
    expect(validateLoginSearch({ return_to: returnTo }).return_to).toBe(returnTo);
  });

  it("drops an absurdly long return_to instead of cutting it", () => {
    expect(
      validateLoginSearch({ return_to: `/oauth/authorize?${"x".repeat(5000)}` }).return_to,
    ).toBeUndefined();
  });
});

describe("validateUsersSearch", () => {
  it("keeps known filters and drops the rest", () => {
    expect(
      validateUsersSearch({ q: " ana ", status: "nope", app: "anpr", offset: "25", create: "true" }),
    ).toEqual({
      q: "ana",
      status: undefined,
      app: "ANPR",
      offset: 25,
      create: true,
    });
  });
});
