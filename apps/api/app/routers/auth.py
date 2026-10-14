from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from ..core.store import insert, scan, list_all, get, update
from ..core.security import hash_pw, verify_pw, make_token
from ..core.tenant import get_ctx
from ..core import audit as auditlog
from ..core import roles as RBAC
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

@router.post("/signup")
def signup(b: Signup):
    if not b.org.strip() or not b.email.strip() or len(b.password) < 8:
        raise HTTPException(400, "org/email required, password min 8 chars")
    tid = str(uuid.uuid4()); uid = str(uuid.uuid4())
    # email must be globally unique (login resolves tenant from email)
    for u in scan("users"):
        if u["email"].lower() == b.email.lower():
            raise HTTPException(409, "email already registered")
    insert("tenants", {"tenant_id": tid}, {"id": tid, "name": b.org.strip()})
    insert("users", {"tenant_id": tid}, {"id": uid, "email": b.email, "password_hash": hash_pw(b.password),
                                         "role": "Owner"})
    auditlog.record({"tenant_id": tid, "user_id": uid, "email": b.email},
                     "signup", f"tenant:{tid}", after={"org": b.org})
    return {"tenant_id": tid, "token": make_token(tid, uid, b.email)}

@router.post("/login")
def login(b: Login):
    for u in scan("users"):
        if u["email"].lower() == b.email.lower() and verify_pw(b.password, u.get("password_hash", "")):
            return {"tenant_id": u["tenant_id"], "token": make_token(u["tenant_id"], u["id"], u["email"]),
                    "role": u.get("role", "Viewer")}
    raise HTTPException(401, "bad credentials")


def _current_user(ctx: dict) -> dict:
    for u in scan("users"):
        if u.get("id") == ctx.get("user_id") and u.get("tenant_id") == ctx.get("tenant_id"):
            return u
    raise HTTPException(401, "unknown user")


@router.get("/me")
def me(ctx: dict = Depends(get_ctx)):
    u = _current_user(ctx)
    return {"user_id": u["id"], "email": u["email"], "role": u.get("role", "Viewer"),
            "tenant_id": ctx["tenant_id"]}


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
    for x in list_all("users", ctx):
        if x["email"].lower() == b.email.lower():
            raise HTTPException(409, "email already in tenant")
    uid = str(uuid.uuid4())
    saved = insert("users", ctx, {"id": uid, "email": b.email,
                                  "password_hash": hash_pw(b.password), "role": b.role})
    auditlog.record(ctx, "user.invite", f"user:{uid}", after={"email": b.email, "role": b.role})
    return {"id": saved["id"], "email": saved["email"], "role": saved["role"]}
