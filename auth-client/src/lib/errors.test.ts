import { describe, expect, it } from "vitest";

import { ApiError, toApiError, userMessage } from "./errors";

function response(status: number, headers: Record<string, string> = {}) {
  return new Response(null, { status, headers });
}

describe("toApiError", () => {
  it("reads the server's {detail: {code, message}}", () => {
    const error = toApiError(response(409), { detail: { code: "last_admin", message: "x" } });
    expect(error).toMatchObject({ status: 409, code: "last_admin" });
  });

  it("collects FastAPI validation errors by field", () => {
    const error = toApiError(response(422), {
      detail: [{ loc: ["body", "username"], msg: "String should match pattern" }],
    });
    expect(error.code).toBe("validation_error");
    expect(error.fields).toEqual({ username: "String should match pattern" });
  });

  it("keeps Retry-After for rate limits", () => {
    const error = toApiError(response(429, { "Retry-After": "120" }), {
      detail: { code: "too_many_attempts", message: "x" },
    });
    expect(error.retryAfter).toBe(120);
    expect(userMessage(error)).toBe("Too many attempts. Try again in 2 minutes.");
  });
});

describe("userMessage", () => {
  it("writes known codes for people, not systems", () => {
    expect(userMessage(new ApiError(401, "invalid_credentials", "raw"))).toMatch(
      /^Incorrect username or password/,
    );
  });

  it("falls back to the server's message for unknown codes", () => {
    expect(userMessage(new ApiError(400, "something_new", "Server says so"))).toBe("Server says so");
  });

  it("explains a network failure", () => {
    expect(userMessage(new TypeError("Failed to fetch"))).toMatch(/Can't reach the server/);
  });
});
