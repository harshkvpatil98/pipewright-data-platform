from __future__ import annotations

import uuid
from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    role: str
    is_active: bool
    email: str | None = None
    display_name: str | None = None
    created_at: datetime
    updated_at: datetime
    # Which tenant this person belongs to. None on a single-tenant install.
    organisation_id: uuid.UUID | None = None
    # Included here so the shell can render the right theme on first paint
    # rather than fetching it and flashing the wrong one.
    preferences: "PreferencesRead" = Field(default_factory=lambda: PreferencesRead())


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead


class BootstrapUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="admin", pattern=r"^(admin|operator|viewer)$")


class UserListResponse(BaseModel):
    """Everyone with an account, for pickers and administration."""

    items: list[UserRead]


class UserUpdateRequest(BaseModel):
    """Change what an existing account may do, or switch it off.

    `is_active=False` is the offboarding path, and the one to reach for first.
    The flag was already checked on every login and on every authenticated
    request; what was missing was any way to set it, so an account could be
    created and never withdrawn. Deactivating keeps the person's name on the
    projects and runs they own, which deleting them cannot.

    Both fields are optional and unset fields are left alone, so switching an
    account off does not silently re-grade it.
    """

    is_active: bool | None = None
    role: str | None = Field(default=None, pattern=r"^(admin|operator|viewer)$")


class UserCreateRequest(BaseModel):
    """Create a colleague an account.

    The platform-wide role here is not the same thing as what someone may do
    inside a project -- that is project membership. This only says whether they
    can administer the platform itself.
    """

    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="viewer", pattern=r"^(admin|operator|viewer)$")
    email: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=120)


# "system" is the default and the only value that stays correct when someone
# changes their OS appearance setting, so it is not merely a third option.
Theme = Literal["light", "dark", "system"]
Density = Literal["comfortable", "compact", "dense"]


class PreferencesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    theme: Theme = "system"
    density: Density = "comfortable"


class PreferencesUpdate(BaseModel):
    """Partial update: omitting a field leaves it alone.

    `None` and "absent" have to mean the same thing here, because a client
    saving only the theme must not silently reset the density.
    """

    theme: Theme | None = None
    density: Density | None = None


class ProfileUpdate(BaseModel):
    """A person edits their own display name and contact email."""

    display_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=255)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class RedeemCodeRequest(BaseModel):
    """Set a password using a one-time activation or reset code."""

    code: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class InviteRequest(BaseModel):
    """Invite a colleague: an inactive account plus a one-time activation code."""

    username: str = Field(min_length=3, max_length=80)
    role: str = Field(default="viewer", pattern=r"^(admin|operator|viewer)$")
    email: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=120)
    organisation_id: uuid.UUID | None = None


class OneTimeCodeResponse(BaseModel):
    """The plaintext code, returned once. A real deployment emails it instead."""

    user_id: uuid.UUID
    username: str
    code: str
    purpose: str
    expires_in_minutes: int


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scope: str = Field(default="read", pattern=r"^(read|write|admin)$")


class ApiTokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prefix: str
    scope: str
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime


class ApiTokenListResponse(BaseModel):
    items: list[ApiTokenRead]


class ApiTokenCreatedResponse(BaseModel):
    """Includes the secret exactly once, at creation."""

    token: ApiTokenRead
    secret: str
