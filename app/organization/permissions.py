"""Organization-role derived workspace permissions."""

from __future__ import annotations

from app.organization.enums import OrganizationRole


def is_organization_manager(role: OrganizationRole) -> bool:
    return role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}


def build_workspace_permission_flags(
    role: OrganizationRole | None,
    *,
    organization_suspended: bool,
    membership_suspended: bool,
) -> dict[str, bool]:
    if role is None or organization_suspended or membership_suspended:
        return {
            "invite_candidate": False,
            "modify_person": False,
            "modify_invitation": False,
            "modify_verification": False,
            "manage_team": False,
            "save_settings": False,
            "transfer_ownership": False,
        }

    can_manage_team = is_organization_manager(role)
    return {
        "invite_candidate": True,
        "modify_person": True,
        "modify_invitation": True,
        "modify_verification": True,
        "manage_team": can_manage_team,
        "save_settings": can_manage_team,
        "transfer_ownership": role == OrganizationRole.OWNER,
    }
