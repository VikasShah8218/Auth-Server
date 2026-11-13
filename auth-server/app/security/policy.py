"""The single file that controls API access.

Key format is "METHOD /route/template". METHOD may be *, and a path ending in * is a prefix rule for a whole
subtree.

    FREE              no token needed
    AUTH              any valid access token issued for this server
    ADMIN             Admin role on the AUTH application
    Rule(...)         roles and/or permission codes
    SelfGuarded(...)  the route authenticates itself

Any route not listed here gets DEFAULT_RULE, so a new endpoint is admin-only until it has its own line. Run
`python -m app.security.policy_audit` to see the effective rule for every route.
"""

from app.security.enforcement import AUTH, FREE, Rule, SelfGuarded

DEFAULT_APP_KEY = "AUTH"

ADMIN = Rule(roles=("Admin",))

DEFAULT_RULE = ADMIN

# Checked at startup against the resolved rule, so a typo can't lock everyone out.
REQUIRED_FREE = {
    "GET /health/live",
    "GET /health/ready",
    "GET /.well-known/openid-configuration",
    "GET /.well-known/jwks.json",
    "GET /oauth/authorize",
    "POST /oauth/token",
    "POST /v1/identity/login",
    "POST /v1/identity/mfa/verify",
    "POST /v1/identity/webauthn/options",
    "POST /v1/identity/webauthn/verify",
    "GET /bff/login",
    "GET /bff/callback",
    "GET /bff/session",
    "POST /bff/logout",
}

POLICY = {
    # Probes send no token.
    "GET /health/live": FREE,
    "GET /health/ready": FREE,

    # Published to the whole world by design.
    "GET /.well-known/openid-configuration": FREE,
    "GET /.well-known/jwks.json": FREE,

    # How a caller gets a token, so they can't require one.
    "POST /v1/identity/login": FREE,
    "POST /v1/identity/mfa/verify": FREE,
    "POST /v1/identity/webauthn/options": FREE,
    "POST /v1/identity/webauthn/verify": FREE,
    "GET /oauth/authorize": SelfGuarded("SSO session cookie"),
    "POST /oauth/token": SelfGuarded("client authentication"),
    "POST /oauth/revoke": SelfGuarded("client authentication"),
    "GET /oauth/userinfo": SelfGuarded("access token for any application"),
    "POST /oauth/logout": SelfGuarded("SSO session cookie or access token"),

    # The console's own session, carried by its cookie.
    "GET /bff/login": FREE,
    "GET /bff/callback": SelfGuarded("state and PKCE"),
    "GET /bff/session": SelfGuarded("console cookie"),
    "POST /bff/logout": SelfGuarded("console cookie and CSRF token"),

    # Downstream servers, on their service tokens.
    "* /v1/events/*": SelfGuarded("service token, scope events.read"),
    "GET /v1/apps/{key}/permission-map": SelfGuarded("service token, scope permissions.read"),
    "GET /v1/apps/{key}/members": SelfGuarded("service token, scope users.read"),
    "GET /v1/apps/{key}/roles": SelfGuarded("service token, scope users.read"),

    # A user acting on their own account.
    "* /v1/me*": AUTH,

    # Everything that manages access.
    "* /v1/admin/*": ADMIN,
}
