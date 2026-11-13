"""Applies app/security/policy.py to every route through one app-level guard.

main.create_app() passes policy_guard to FastAPI(dependencies=[...]), so the guard runs for every route,
including any added later, and each rule is resolved per request. It uses only public FastAPI API: the old
server inserted guards into each route after startup, which misses lazily included routers and reports
success while the routes stay open.

Two conditions keep it fail-closed:

  * A route the guard can't identify is denied. scope["route"].path leaves out a prefix given to
    include_router(), so routers must carry their full prefix themselves. A route breaking that rule gets
    403 instead of a wrong rule.
  * apply_security_policy() refuses to start if the guard isn't installed.

Resolution order: exact "METHOD /path" > "* /path" > longest "METHOD /prefix*" > longest "* /prefix*"
> DEFAULT_RULE.
"""

from dataclasses import dataclass, field

from fastapi import Depends, FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.applications.models import Permission
from app.console.services import claims_from_cookie
from app.tokens import services as token_services
from app.tokens.schemas import Claims
from utilities.exceptions import AppError
from utilities.masks import decode_mask, grants

FREE = "FREE"
AUTH = "AUTH"

_HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}
_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Rule:
    """Roles and/or permission codes required on an application.

    app_key None means the policy's default application. Every application has a role named "Admin", so a
    role must never be accepted from any app by accident. Accepting one on purpose takes cross_app=True.
    """

    roles: tuple[str, ...] = ()
    perms: tuple[str, ...] = ()
    any_role: bool = True
    any_perm: bool = True
    app_key: str | None = None
    cross_app: bool = False


@dataclass(frozen=True)
class SelfGuarded:
    """The route authenticates itself, for example with client credentials."""

    reason: str


def _normalise_path(path: str) -> str:
    return path.rstrip("/") or "/"


def _parse_key(key: str) -> tuple[str, str]:
    parts = key.split()
    if len(parts) != 2:
        raise ValueError(f"Bad policy key {key!r}: expected 'METHOD /path'")
    return parts[0].upper(), parts[1]


@dataclass
class CompiledPolicy:
    exact: dict[tuple[str, str], object] = field(default_factory=dict)
    prefixes: list[tuple[str, str, object]] = field(default_factory=list)
    default: object = None
    default_app_key: str = ""

    @classmethod
    def build(cls, policy: dict, default: object, default_app_key: str) -> "CompiledPolicy":
        compiled = cls(default=default, default_app_key=default_app_key)
        for key, rule in policy.items():
            method, path = _parse_key(key)
            if path.endswith("*"):
                compiled.prefixes.append((method, path[:-1], rule))
                continue
            target = (method, _normalise_path(path))
            if target in compiled.exact:
                raise ValueError(f"Duplicate policy entry for {key!r}")
            compiled.exact[target] = rule
        # Longest prefix first. A named method beats "*" at equal length.
        compiled.prefixes.sort(key=lambda e: (len(e[1]), e[0] != "*"), reverse=True)
        return compiled

    def resolve(self, method: str, path: str) -> tuple[object, str]:
        path = _normalise_path(path)
        if (method, path) in self.exact:
            return self.exact[(method, path)], f"exact:{method} {path}"
        if ("*", path) in self.exact:
            return self.exact[("*", path)], f"exact:* {path}"
        for rule_method, prefix, rule in self.prefixes:
            if rule_method in (method, "*") and path.startswith(prefix):
                return rule, f"prefix:{rule_method} {prefix}*"
        return self.default, "default"


async def _permission_bits(app_key: str, codes: tuple[str, ...]) -> list[int]:
    return await Permission.filter(app__key=app_key, code__in=codes, retired_at__isnull=True).values_list(
        "bit", flat=True
    )


async def _enforce_rule(rule: Rule, claims: Claims, default_app_key: str) -> None:
    app_key = None if rule.cross_app else (rule.app_key or default_app_key)
    if app_key is not None and claims.aud != app_key:
        raise AppError(403, "wrong_application", "Token is not valid for this application")

    if rule.roles:
        held = set(claims.roles)
        required = set(rule.roles)
        allowed = bool(held & required) if rule.any_role else required <= held
        if not allowed:
            raise AppError(403, "insufficient_role", "Your role does not allow this action")

    if rule.perms:
        try:
            mask = decode_mask(claims.pm)
        except ValueError:
            raise AppError(401, "invalid_token", "Token could not be verified") from None
        bits = await _permission_bits(claims.aud, rule.perms)
        granted = [bit for bit in bits if grants(mask, bit)]
        # A code that no longer exists has no bit, so it counts as not held.
        allowed = bool(granted) if rule.any_perm else (len(bits) == len(set(rule.perms)) and len(granted) == len(bits))
        if not allowed:
            raise AppError(403, "insufficient_permission", "You do not have this permission")


async def policy_guard(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> None:
    compiled: CompiledPolicy | None = getattr(request.app.state, "security_policy", None)
    route = request.scope.get("route")
    if compiled is None or not isinstance(route, APIRoute) or route.path_regex.fullmatch(request.scope["path"]) is None:
        raise AppError(403, "policy_unresolved", "Access denied")

    rule, _ = compiled.resolve(request.method, route.path)
    if rule == FREE or isinstance(rule, SelfGuarded):
        return

    if credentials is not None:
        claims = await token_services.verify_access_token(credentials.credentials)
    else:
        # The admin console carries no bearer token: its identity comes from its HttpOnly cookie.
        claims = await claims_from_cookie(request)
    if claims is None:
        raise AppError(401, "not_authenticated", "Authentication required", _UNAUTHORIZED_HEADERS)

    # A delegated token acts for a service, and this API manages access itself.
    if claims.act is not None:
        raise AppError(403, "delegated_token", "Delegated tokens can't use this API")

    request.state.claims = claims
    if rule == AUTH:
        # This server's API takes tokens issued for it, not an ANPR token.
        if claims.aud != compiled.default_app_key:
            raise AppError(403, "wrong_application", "Token is not valid for this application")
        return
    if not isinstance(rule, Rule):
        raise AppError(403, "policy_unresolved", "Access denied")
    await _enforce_rule(rule, claims, compiled.default_app_key)


def _rule_label(rule: object, default_app_key: str) -> str:
    if isinstance(rule, SelfGuarded):
        return f"SELF:{rule.reason}"
    if isinstance(rule, Rule):
        parts = []
        if rule.roles:
            parts.append(("" if rule.any_role else "all-of:") + "roles:" + ",".join(rule.roles))
        if rule.perms:
            parts.append(("" if rule.any_perm else "all-of:") + "perms:" + ",".join(rule.perms))
        scope = "ANY-APP" if rule.cross_app else (rule.app_key or default_app_key)
        return f"{' '.join(parts) or 'TOKEN'}@{scope}"
    return str(rule)


def _guard_installed(app: FastAPI) -> bool:
    return any(dep.dependency is policy_guard for dep in app.router.dependencies)


def apply_security_policy(
    app: FastAPI,
    policy: dict | None = None,
    default: object = None,
    default_app_key: str | None = None,
    required_free: set[str] | None = None,
) -> list[tuple[str, str, str, str]]:
    """Check the policy against the app's routes and activate it.

    Returns audit rows of (method, path, rule, source). Raises RuntimeError on a missing guard, a policy key
    matching no route, or a required public endpoint that resolves to anything but FREE or SelfGuarded.
    """
    from app.security import policy as api_policy

    policy = api_policy.POLICY if policy is None else policy
    default = api_policy.DEFAULT_RULE if default is None else default
    default_app_key = default_app_key or api_policy.DEFAULT_APP_KEY
    if required_free is None:
        required_free = api_policy.REQUIRED_FREE

    if not _guard_installed(app):
        raise RuntimeError("policy_guard is not installed as an app-level dependency")

    compiled = CompiledPolicy.build(policy, default, default_app_key)
    used: set[str] = set()
    resolved: dict[str, object] = {}
    rows = []

    # openapi() is the public view of every route, including lazily included ones.
    for path, operations in app.openapi()["paths"].items():
        for method in sorted(m.upper() for m in operations if m in _HTTP_METHODS):
            rule, source = compiled.resolve(method, path)
            used.add(source)
            resolved[f"{method} {_normalise_path(path)}"] = rule
            rows.append((method, path, _rule_label(rule, default_app_key), source))
    app.openapi_schema = None

    for key in sorted(required_free):
        method, path = _parse_key(key)
        rule = resolved.get(f"{method} {_normalise_path(path)}")
        if not (rule == FREE or isinstance(rule, SelfGuarded)):
            raise RuntimeError(f"{key} must resolve to FREE or SelfGuarded")

    dead = [f"{method} {path}" for method, path in compiled.exact if f"exact:{method} {path}" not in used]
    dead += [
        f"{method} {prefix}*" for method, prefix, _ in compiled.prefixes if f"prefix:{method} {prefix}*" not in used
    ]
    if dead:
        raise RuntimeError(f"Policy entries match no route: {sorted(dead)}")

    app.state.security_policy = compiled
    return rows
