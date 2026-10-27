"""Workspace roles and the permissions they grant (docs/v2/03-contracts.md)."""

_VIEW = {"connection.read", "catalog.read", "pipeline.read", "run.read"}
ROLE_PERMS = {
    "viewer": _VIEW,
    "author": _VIEW | {"preview.run", "pipeline.write", "pipeline.submit_review"},
    "reviewer": _VIEW | {"approval.decide"},
    "operator": _VIEW | {"preview.run", "run.submit", "run.cancel", "run.retry"},
}
ROLE_PERMS["admin"] = set().union(*ROLE_PERMS.values()) | {"connection.manage", "settings.manage", "user.manage"}
ROLES = tuple(ROLE_PERMS)


def allowed(role, permission):
    return permission in ROLE_PERMS.get(role, ())
