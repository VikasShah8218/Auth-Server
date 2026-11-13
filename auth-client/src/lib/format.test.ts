import { describe, expect, it } from "vitest";

import { amrLabel, daysUntil, deviceLabel, initials, userInitials } from "./format";

describe("deviceLabel", () => {
  it.each([
    [
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
      "Chrome on Windows",
      false,
    ],
    [
      "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/131.0 Safari/537.36 Edg/131.0",
      "Edge on Windows",
      false,
    ],
    [
      "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
      "Safari on iPhone",
      true,
    ],
    ["python-httpx/0.27.0", "Script", false],
  ])("%s", (ua, label, mobile) => {
    expect(deviceLabel(ua)).toEqual({ label, mobile });
  });

  it("handles a missing user agent", () => {
    expect(deviceLabel(null).label).toBe("Unknown device");
  });
});

describe("amrLabel", () => {
  it("names the second factor", () => {
    expect(amrLabel(["pwd"])).toBe("Password");
    expect(amrLabel(["pwd", "otp"])).toBe("Password + authenticator");
    expect(amrLabel(["pwd", "hwk"])).toBe("Password + security key");
  });
});

describe("initials", () => {
  it("uses names, then the username", () => {
    expect(initials("Imran", "Khan")).toBe("IK");
    expect(initials("aditi.rao")).toBe("AR");
    expect(initials("admin")).toBe("AD");
    expect(initials(null, undefined)).toBe("");
  });

  it("falls back from names to the username", () => {
    expect(userInitials({ username: "e2e.admin", first_name: null, last_name: null })).toBe("EA");
    expect(userInitials({ username: "imran.k", first_name: "Imran", last_name: "Khan" })).toBe("IK");
  });
});

describe("daysUntil", () => {
  it("counts whole days, rounding up", () => {
    const now = Date.UTC(2026, 10, 13, 12);
    expect(daysUntil(new Date(now + 36 * 3600 * 1000), now)).toBe(2);
    expect(daysUntil(null, now)).toBeNull();
  });
});
