/**
 * Server errors arrive as {"detail": {"code", "message"}} (or FastAPI's 422 list). ApiError carries the code,
 * and userMessage() turns it into text written for the person using the console.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfter: number | null;
  readonly fields: Record<string, string>;

  constructor(status: number, code: string, message: string, retryAfter: number | null = null, fields = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
    this.fields = fields;
  }
}

type ValidationItem = { loc?: (string | number)[]; msg?: string };

export function toApiError(response: Response, body: unknown): ApiError {
  const retry = Number(response.headers.get("Retry-After"));
  const retryAfter = Number.isFinite(retry) && retry > 0 ? retry : null;
  const detail = (body as { detail?: unknown } | null)?.detail;

  if (detail && typeof detail === "object" && !Array.isArray(detail) && "code" in detail) {
    const { code, message } = detail as { code: string; message: string };
    return new ApiError(response.status, code, message, retryAfter);
  }
  if (Array.isArray(detail)) {
    const fields: Record<string, string> = {};
    for (const item of detail as ValidationItem[]) {
      const field = item.loc?.filter((part) => part !== "body").join(".") ?? "";
      if (field && item.msg) fields[field] = item.msg.replace(/^Value error, /, "");
    }
    const first = Object.values(fields)[0] ?? "Some fields are not valid.";
    return new ApiError(response.status, "validation_error", first, null, fields);
  }
  return new ApiError(response.status, `http_${response.status}`, response.statusText || "Request failed");
}

const MESSAGES: Record<string, string> = {
  invalid_credentials: "Incorrect username or password. Check both and try again.",
  invalid_code: "That code isn't valid. Check your authenticator app and try again.",
  invalid_credential: "The security key couldn't be verified. Try again, or use your authenticator app.",
  mfa_challenge_expired: "Your sign-in timed out. Enter your password again.",
  temporarily_unavailable: "Sign-in is unavailable right now. Try again in a minute.",
  not_authenticated: "Your session has ended. Sign in again.",
  invalid_token: "Your session has ended. Sign in again.",
  insufficient_role: "You don't have permission to do this.",
  insufficient_permission: "You don't have permission to do this.",
  csrf_failed: "This page is out of date. Reload it and try again.",
  last_admin: "At least one active administrator must remain.",
  protected: "This is protected and can't be changed this way.",
  weak_password: "Use at least 12 characters, and don't include the username.",
  user_exists: "That username or email is already in use.",
  application_exists: "An application with this key already exists.",
  permission_exists: "This permission already exists.",
  permission_limit: "This application has reached its 1,024 permission limit.",
  role_exists: "A role with this name already exists.",
  client_exists: "A client with this ID already exists.",
  mfa_already_enabled: "Authenticator app sign-in is already on.",
  no_enrolment: "Start the authenticator setup again.",
  internal_error: "Something went wrong on the server. Try again.",
};

export function userMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "too_many_attempts") {
      const minutes = error.retryAfter ? Math.max(1, Math.ceil(error.retryAfter / 60)) : null;
      return minutes
        ? `Too many attempts. Try again in ${minutes} minute${minutes === 1 ? "" : "s"}.`
        : "Too many attempts. Try again later.";
    }
    return MESSAGES[error.code] ?? error.message;
  }
  if (error instanceof TypeError) return "Can't reach the server. Check your connection and try again.";
  return "Something went wrong. Try again.";
}
