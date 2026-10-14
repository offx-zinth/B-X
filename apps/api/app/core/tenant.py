"""Tenant isolation: never trust frontend. Every query filters tenant_id from JWT."""
from fastapi import Depends, HTTPException, Header

from .security import decode_token

def get_ctx(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        data = decode_token(authorization[7:])
    except Exception:
        raise HTTPException(401, "invalid token")
    if "tenant_id" not in data or "sub" not in data:
        raise HTTPException(401, "tenant scope missing")
    return {"tenant_id": data["tenant_id"], "user_id": data["sub"], "email": data.get("email", "")}

def scoped(query_dict: dict, ctx: dict) -> dict:
    """Helper for in-memory/dict stores: enforce tenant_id."""
    return {**query_dict, "tenant_id": ctx["tenant_id"]}
