"""RBAC: Organization -> Workspace -> Users -> Roles -> Permissions.

Roles: Owner > Admin > Analyst > Viewer. Stored on the ``users`` record as
``role``. Signup creates the org Owner; later invites assign lesser roles.
Permission checks are backend-enforced (never frontend-only).
"""
from __future__ import annotations
from fastapi import HTTPException

ROLES = ("Owner", "Admin", "Analyst", "Viewer")
_RANK = {r: i for i, r in enumerate(("Viewer", "Analyst", "Admin", "Owner"))}

# action -> minimum role required
POLICY: dict[str, str] = {
    "graph.read": "Viewer",
    "graph.write": "Analyst",
    "ingest.write": "Analyst",
    "formula.write": "Analyst",
    "formula.approve": "Admin",
    "simulation.write": "Analyst",
    "report.read": "Viewer",
    "report.write": "Analyst",
    "admin.write": "Admin",
    "owner.write": "Owner",
}


def role_of(user: dict) -> str:
    r = (user or {}).get("role", "Viewer")
    return r if r in _RANK else "Viewer"


def can(role: str, action: str) -> bool:
    need = POLICY.get(action, "Admin")
    return _RANK.get(role, 0) >= _RANK.get(need, 99)


def require(user: dict, action: str) -> str:
    role = role_of(user)
    if not can(role, action):
        raise HTTPException(403, f"role {role} cannot perform {action}")
    return role
