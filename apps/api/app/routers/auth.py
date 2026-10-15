from fastapi import APIRouter, HTTPException, Depends, Response, Request
from pydantic import BaseModel
from ..core.store import insert, scan, list_all, update, find_user_by_email, get_user
from ..core.security import hash_pw, verify_pw, needs_rehash, make_token, make_access_token, make_refresh_token, decode_token
from ..core.tenant import get_ctx
from ..core import audit as auditlog
from ..core import roles as RBAC
from ..core.config import settings
import uuid

router = APIRouter(prefix="/auth", tags=["auth"])


class Signup(BaseModel):
    org: str
    email: str
    password: str


class Login(BaseModel):
    email: str
    password: str


class Invite(BaseModel):
    email: str
    password: str
    role: str = "Viewer"


def _set_auth_cookies(resp: Response, access: str, refresh: str) -> None:
    secure = settings.COOKIE_SECURE
    extra = {}
    if settings.COOKIE_DOMAIN:
        extra["domain"] = settings.COOKIE_DOMAIN
    resp.set_cookie("access_token", access, httponly=True, secure=secure, samesite="lax",
                    max_age=settings.JWT_ACCESS_MINUTES * 60, path="/", **extra)
    resp.set_cookie("refresh_token", refresh, httponly=True, secure=secure, samesite="lax",
                    max_age=settings.JWT_REFRESH_DAYS * 86400, path="/auth", **extra)


def _tokens_for(user: dict) -> tuple[str, str, str]:
    access = make_access_token(user["tenant_id"], user["id"], user["email"],
                               user.get("role", "Viewer"))
    refresh = make_refresh_token(user["tenant_id"], user["id"])
    legacy = make_token(user["tenant_id"], user["id"], user["email"])
    return access, refresh, legacy


@router.post("/signup")
def signup(b: Signup, response: Response):
    if not b.org.strip() or not b.email.strip() or len(b.password) < 8:
        raise HTTPException(400, "org/email required, password min 8 chars")
    tid = str(uuid.uuid4())
    uid = str(uuid.uuid4())
    # email must be globally unique (login resolves tenant from email)
    if find_user_by_email(b.email):
        raise HTTPException(409, "email already registered")
    insert("tenants", {"tenant_id": tid}, {"id": tid, "name": b.org.strip()})
    insert("users", {"tenant_id": tid}, {"id": uid, "email": b.email, "password_hash": hash_pw(b.password),
                                         "role": "Owner"})
    auditlog.record({"tenant_id": tid, "user_id": uid, "email": b.email},
                     "signup", f"tenant:{tid}", after={"org": b.org})
    access, refresh, legacy = _tokens_for({"tenant_id": tid, "id": uid, "email": b.email, "role": "Owner"})
    _set_auth_cookies(response, access, refresh)
    # refresh token returned for non-browser clients; browsers use HttpOnly cookie
    return {"tenant_id": tid, "token": legacy, "access_token": access, "refresh_token": refresh}


@router.post("/login")
def login(b: Login, response: Response):
    u = find_user_by_email(b.email)
    if not u or not verify_pw(b.password, u.get("password_hash", "")):
        raise HTTPException(401, "bad credentials")
    if needs_rehash(u.get("password_hash", "")):
        try:
            update("users", {"tenant_id": u["tenant_id"]}, u["id"], {"password_hash": hash_pw(b.password)})
        except Exception:
            pass
    access, refresh, legacy = _tokens_for(u)
    _set_auth_cookies(response, access, refresh)
    return {"tenant_id": u["tenant_id"], "token": legacy, "access_token": access,
            "refresh_token": refresh, "role": u.get("role", "Viewer")}


class RefreshIn(BaseModel):
    refresh_token: str = ""


@router.post("/refresh")
def refresh(request: Request, response: Response, body: RefreshIn | None = None):
    raw = request.cookies.get("refresh_token") or ""
    if not raw and body and body.refresh_token:
        raw = body.refresh_token
    if not raw:
        raise HTTPException(401, "missing refresh token")
    try:
        data = decode_token(raw)
    except Exception:
        raise HTTPException(401, "invalid refresh token")
    if data.get("typ") != "refresh":
        raise HTTPException(401, "not a refresh token")
    u = get_user(data.get("tenant_id", ""), data.get("sub", ""))
    if not u:
        raise HTTPException(401, "unknown user")
    access = make_access_token(u["tenant_id"], u["id"], u["email"], u.get("role", "Viewer"))
    new_refresh = make_refresh_token(u["tenant_id"], u["id"])  # sliding expiration
    _set_auth_cookies(response, access, new_refresh)
    return {"tenant_id": u["tenant_id"], "token": make_token(u["tenant_id"], u["id"], u["email"]),
            "access_token": access, "refresh_token": new_refresh}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/auth")
    return {"ok": True}


def _current_user(ctx: dict) -> dict:
    u = get_user(ctx.get("tenant_id", ""), ctx.get("user_id", ""))
    if not u:
        raise HTTPException(401, "unknown user")
    return u


@router.get("/me")
def me(ctx: dict = Depends(get_ctx)):
    u = _current_user(ctx)
    return {"user_id": u["id"], "email": u["email"], "role": u.get("role", "Viewer"),
            "tenant_id": ctx["tenant_id"]}


@router.get("/tenant")
def tenant(ctx: dict = Depends(get_ctx)):
    """Current tenant with usage counts for the workspace switcher."""
    from ..core.store import list_all as _list
    u = _current_user(ctx)
    tname = ctx["tenant_id"]
    for t in scan("tenants"):
        if t.get("id") == ctx["tenant_id"]:
            tname = t.get("name", tname)
            break
    return {"tenant_id": ctx["tenant_id"], "name": tname,
            "email": u["email"], "role": u.get("role", "Viewer"),
            "users": len(_list("users", ctx)),
            "nodes": len(_list("nodes", ctx)), "edges": len(_list("edges", ctx)),
            "formulas": len(_list("formulas", ctx)),
            "sources": len(_list("data_sources", ctx))}


@router.get("/users")
def users(ctx: dict = Depends(get_ctx)):
    u = _current_user(ctx)
    RBAC.require(u, "admin.write")
    return [{"id": x["id"], "email": x["email"], "role": x.get("role", "Viewer")}
            for x in list_all("users", ctx)]


@router.post("/users")
def invite(b: Invite, ctx: dict = Depends(get_ctx)):
    u = _current_user(ctx)
    RBAC.require(u, "admin.write")
    if b.role not in RBAC.ROLES:
        raise HTTPException(400, f"role must be one of {RBAC.ROLES}")
    if len(b.password) < 8:
        raise HTTPException(400, "password min 8 chars")
    if find_user_by_email(b.email) and find_user_by_email(b.email).get("tenant_id") == ctx["tenant_id"]:
        raise HTTPException(409, "email already in tenant")
    # global uniqueness: login resolves tenant from email
    if find_user_by_email(b.email):
        raise HTTPException(409, "email already registered")
    uid = str(uuid.uuid4())
    saved = insert("users", ctx, {"id": uid, "email": b.email,
                                  "password_hash": hash_pw(b.password), "role": b.role})
    auditlog.record(ctx, "user.invite", f"user:{uid}", after={"email": b.email, "role": b.role})
    return {"id": saved["id"], "email": saved["email"], "role": saved["role"]}
