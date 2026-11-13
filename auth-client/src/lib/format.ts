/** Formatting with the browser's Intl: no date library. */

const dateFormat = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" });
const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const shortDate = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });
const numberFormat = new Intl.NumberFormat();
const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto", style: "short" });

type DateInput = string | number | Date | null | undefined;

function toDate(value: DateInput): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(value: DateInput): string {
  const date = toDate(value);
  return date ? dateFormat.format(date) : "—";
}

export function formatDateTime(value: DateInput): string {
  const date = toDate(value);
  return date ? dateTimeFormat.format(date) : "—";
}

export function formatShortDate(value: DateInput): string {
  const date = toDate(value);
  return date ? shortDate.format(date) : "—";
}

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : numberFormat.format(value);
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
  ["second", 1],
];

/** "3 min ago", "in 12 days". */
export function formatRelative(value: DateInput, now: number = Date.now()): string {
  const date = toDate(value);
  if (!date) return "—";
  const seconds = Math.round((date.getTime() - now) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 5) return "just now";
  for (const [unit, size] of UNITS) {
    if (abs >= size || unit === "second") return relative.format(Math.round(seconds / size), unit);
  }
  return relative.format(seconds, "second");
}

/** Whole days from now until the date (negative when past). */
export function daysUntil(value: DateInput, now: number = Date.now()): number | null {
  const date = toDate(value);
  return date ? Math.ceil((date.getTime() - now) / (24 * 3600 * 1000)) : null;
}

/** "Chrome on Windows" from a user agent string. Good enough for a sessions list. */
export function deviceLabel(userAgent: string | null | undefined): { label: string; mobile: boolean } {
  if (!userAgent) return { label: "Unknown device", mobile: false };
  const ua = userAgent;
  const browser = /Edg\//.test(ua)
    ? "Edge"
    : /OPR\//.test(ua)
      ? "Opera"
      : /Firefox\//.test(ua)
        ? "Firefox"
        : /Chrome\//.test(ua)
          ? "Chrome"
          : /Safari\//.test(ua)
            ? "Safari"
            : /python|httpx|curl/i.test(ua)
              ? "Script"
              : "Browser";
  const os = /iPhone|iPad/.test(ua)
    ? "iPhone"
    : /Android/.test(ua)
      ? "Android"
      : /Windows/.test(ua)
        ? "Windows"
        : /Mac OS X|Macintosh/.test(ua)
          ? "macOS"
          : /Linux/.test(ua)
            ? "Linux"
            : null;
  const mobile = /iPhone|iPad|Android|Mobile/.test(ua);
  return { label: os ? `${browser} on ${os}` : browser, mobile };
}

/** How the user signed in, from the session's amr list. */
export function amrLabel(amr: string[]): string {
  const second = amr.includes("hwk") ? "security key" : amr.includes("otp") ? "authenticator" : null;
  return second ? `Password + ${second}` : "Password";
}

/** Two letters from names or a username; "" when there's nothing to use. */
export function initials(...parts: (string | null | undefined)[]): string {
  const words = parts
    .filter(Boolean)
    .join(" ")
    .trim()
    .split(/[\s._-]+/)
    .filter(Boolean);
  if (words.length === 0) return "";
  const first = words[0][0] ?? "";
  const second = words.length > 1 ? (words[1][0] ?? "") : (words[0][1] ?? "");
  return (first + second).toUpperCase();
}

/** Avatar letters for a person: their name, else their username. */
export function userInitials(user: {
  username: string;
  first_name?: string | null;
  last_name?: string | null;
}): string {
  return initials(user.first_name, user.last_name) || initials(user.username) || "?";
}

export function fullName(user: { first_name?: string | null; last_name?: string | null }): string {
  return [user.first_name, user.last_name].filter(Boolean).join(" ");
}
