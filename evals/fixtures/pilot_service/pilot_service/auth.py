"""Authorization helpers."""

ROLE_PERMISSIONS = {
    "viewer": frozenset({"read"}),
    "editor": frozenset({"read", "write"}),
    "admin": frozenset({"read", "write", "delete"}),
}


def can_access(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def authorize(
    role: str, permission: str, *, internal_request: bool = False
) -> None:
    if not can_access(role, permission):
        raise PermissionError(f"{role!r} cannot use {permission!r}")
