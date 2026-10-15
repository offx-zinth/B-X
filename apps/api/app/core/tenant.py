"""Tenant isolation: never trust frontend. Every query filters tenant_id from JWT.

Supports Bearer tokens (back-compat, tests, API clients) and HttpOnly cookies
(access_token) set on login/signup. Fail-closed: missing/empty tenant scope
always 401s, never falls through to a default role.
"""
from fastapi import Depends, HTTPException, Header, Request

from .security import decode_token


def _decode_bearer(authorization: str) -> dict | None:
    if not authorization.startswith("Bearer "):
        return None
    try:
        return decode_token(authorization[7:])
    except Exception:
        raise HTTPException(401, "invalid token")


def get_ctx(request: Request, authorization: str = Header(default="")) -> dict:
    data: dict | None = None
    if authorization.startswith("Bearer "):
        data = _decode_bearer(authorization)
    if data is None:
        cookie_tok = request.cookies.get("access_token")
        if cookie_tok:
            try:
                data = decode_token(cookie_tok)
            except Exception:
                raise HTTPException(401, "invalid token")
    if data is None:
        raise HTTPException(401, "missing bearer token")
    if not data.get("tenant_id") or not data.get("sub"):
        raise HTTPException(401, "tenant scope missing")
    return {"tenant_id": data["tenant_id"], "user_id": data["sub"],
            "email": data.get("email", ""), "role": data.get("role", "")}


def scoped(query_dict: dict, ctx: dict) -> dict:
    """Helper for in-memory/dict stores: enforce tenant_id."""
    return {**query_dict, "tenant_id": ctx["tenant_id"]}


def get_user_record(ctx: dict) -> dict:
    """Indexed tenant-scoped user fetch. Raises 401, never defaults to Viewer."""
    from . import store as _store
    u = _store.get_user(ctx.get("tenant_id", ""), ctx.get("user_id", ""))
    if not u:
        raise HTTPException(401, "unknown user")
    return u


def require_action(action: str):
    """FastAPI dependency factory enforcing fine-grained RBAC scopes.

    Usage: ``commons: dict = Depends(require_action("formula:approve"))``.
    Maps ``scope="formula:approve"`` style scopes onto the RBAC policy.
    """
    from . import roles as RBAC

    def _dep(ctx: dict = Depends(get_ctx)) -> dict:
        u = get_user_record(ctx)
        policy_action = action.replace(":", ".")
        RBAC.require(u, policy_action)
        return {"ctx": ctx, "user": u}
    return _dep
