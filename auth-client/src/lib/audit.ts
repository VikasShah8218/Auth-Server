/** Audit actions in plain words. Unknown actions fall back to their code. */

export const AUDIT_ACTIONS: Record<string, string> = {
  "admin.bootstrap": "First administrator created",
  "application.create": "Application created",
  "application.update": "Application updated",
  "permission.create": "Permission created",
  "permission.update": "Permission updated",
  "permission.retire": "Permission retired",
  "role.create": "Role created",
  "role.update": "Role updated",
  "role.delete": "Role deleted",
  "role.set_permissions": "Role permissions changed",
  "user.create": "User created",
  "user.update": "User updated",
  "user.set_roles": "Roles changed",
  "user.login": "Signed in",
  "user.password_change": "Password changed",
  "user.password_reset": "Password reset by an admin",
  "session.revoke": "Session ended",
  "session.revoke_all": "All sessions ended",
  "mfa.enable": "MFA factor added",
  "mfa.disable": "MFA factor removed",
  "mfa.reset": "MFA reset by an admin",
  "client.create": "Client created",
  "client.update": "Client updated",
  "client.rotate_secret": "Client secret rotated",
  "key.rotate": "Signing key rotated",
  "key.revoke": "Signing key revoked",
  "token.exchange": "Token exchanged",
  "token.reuse_detected": "Refresh token reuse detected",
};

export function auditLabel(action: string): string {
  return AUDIT_ACTIONS[action] ?? action;
}

/** Actions worth flagging in a list. */
export function isAlarming(action: string): boolean {
  return action === "token.reuse_detected" || action === "key.revoke" || action === "mfa.reset";
}
