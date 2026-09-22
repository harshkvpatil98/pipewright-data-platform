from __future__ import annotations

import uuid

from sqlalchemy import Uuid, bindparam, func, select, text
from sqlalchemy.orm import Session

from service_auth.models import User, UserPreference
from service_auth.schemas import (
    InviteRequest,
    BootstrapUserRequest,
    PreferencesRead,
    PreferencesUpdate,
    UserCreateRequest,
    UserRead,
    UserUpdateRequest,
)
from shared_python.auth.security import hash_password, verify_password
from shared_python.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    UnauthorizedError,
)


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def get_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def create_user(db: Session, payload: BootstrapUserRequest | UserCreateRequest) -> User:
    if get_user_by_username(db, payload.username) is not None:
        raise ConflictError("A user with that username already exists.")

    user = User(
        username=payload.username.strip().lower(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
        email=(getattr(payload, "email", None) or None),
        display_name=(getattr(payload, "display_name", None) or None),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, username: str, password: str) -> User:
    user = get_user_by_username(db, username.strip().lower())
    if user is None or not verify_password(password, user.password_hash):
        raise UnauthorizedError("Invalid username or password.")
    if not user.is_active:
        raise UnauthorizedError("User account is inactive.")
    return user


def change_password(db: Session, *, user_id: uuid.UUID, current: str, new: str) -> None:
    """Change a person's own password, ending every existing session.

    The current password is required even though the caller is authenticated:
    it stops a walked-up-to, still-logged-in browser from being used to lock
    the real owner out. Bumping `token_version` invalidates the JWT this very
    request arrived on, so the client re-authenticates with the new password.
    """
    user = _require_user(db, user_id)
    if not verify_password(current, user.password_hash):
        raise BadRequestError("Your current password is incorrect.")
    if len(new) < 8:
        raise BadRequestError("A password must be at least 8 characters.")
    if verify_password(new, user.password_hash):
        raise BadRequestError("The new password must be different from the old one.")
    user.password_hash = hash_password(new)
    user.token_version += 1
    db.commit()


def set_password_with_code(db: Session, *, code: str, new: str, purpose: str | None = None) -> User:
    """Set a password by redeeming a one-time activation or reset code.

    Activation also switches the account on: an invited account is created
    inactive precisely so it cannot be signed into before its owner sets a
    password. Either way every prior session ends.
    """
    from service_auth.codes import ACTIVATION, redeem_code

    if len(new) < 8:
        raise BadRequestError("A password must be at least 8 characters.")
    user_id, redeemed_purpose = redeem_code(db, code=code, purpose=purpose)
    user = _require_user(db, user_id)
    user.password_hash = hash_password(new)
    user.token_version += 1
    if redeemed_purpose == ACTIVATION:
        user.is_active = True
    db.commit()
    db.refresh(user)
    return user


def sign_out_everywhere(db: Session, *, user_id: uuid.UUID) -> None:
    """End all of a user's sessions by bumping their token version."""
    user = _require_user(db, user_id)
    user.token_version += 1
    db.commit()


def invite_user(db: Session, payload: "InviteRequest") -> tuple[User, str]:
    """Create an account that activates itself with a one-time code.

    The account is inactive until the code is redeemed, so an invite that is
    never accepted is never a way in. Returns the user and the plaintext code
    (which a real deployment would email rather than hand back).
    """
    from service_auth.codes import ACTIVATION, issue_code

    if get_user_by_username(db, payload.username) is not None:
        raise ConflictError("A user with that username already exists.")
    user = User(
        username=payload.username.strip().lower(),
        # A random unusable secret: the account cannot be signed into until the
        # activation code sets a real password.
        password_hash=hash_password(uuid.uuid4().hex + uuid.uuid4().hex),
        role=payload.role,
        is_active=False,
        email=(payload.email or None),
        display_name=(payload.display_name or None),
        organisation_id=payload.organisation_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    code = issue_code(db, user_id=user.id, purpose=ACTIVATION)
    return user, code


def update_profile(
    db: Session, *, user_id: uuid.UUID, display_name: str | None, email: str | None
) -> User:
    """A person edits their own name and contact email."""
    user = _require_user(db, user_id)
    if display_name is not None:
        user.display_name = display_name.strip() or None
    if email is not None:
        user.email = email.strip() or None
    db.commit()
    db.refresh(user)
    return user


def _require_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found.")
    return user


def list_users(db: Session, *, limit: int = 200) -> list[User]:
    """Everyone with an account, oldest first."""
    return list(
        db.scalars(select(User).order_by(User.created_at.asc()).limit(limit)).all()
    )


#: Projects this person owns. Raw SQL for the same reason `service_projects`
#: counts datasets that way: `service_projects` imports this package's schemas,
#: so importing its models back would be a cycle. The bind parameter is typed
#: explicitly because an untyped one is handed straight to the driver, which
#: works on Postgres and fails on the SQLite the tests run against.
_COUNT_OWNED_PROJECTS = text(
    "SELECT COUNT(*) FROM projects WHERE owner_user_id = :user_id"
).bindparams(bindparam("user_id", type_=Uuid(as_uuid=True)))


def owned_project_count(db: Session, user_id: uuid.UUID) -> int:
    return db.execute(_COUNT_OWNED_PROJECTS, {"user_id": user_id}).scalar_one() or 0


def _get_user_or_404(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found.")
    return user


def _other_active_admins(db: Session, user_id: uuid.UUID) -> int:
    """Admins who could still administer the platform without this one."""
    return (
        db.scalar(
            select(func.count(User.id)).where(
                User.role == "admin", User.is_active.is_(True), User.id != user_id
            )
        )
        or 0
    )


def update_user(
    db: Session, user_id: uuid.UUID, payload: UserUpdateRequest, actor: UserRead
) -> User:
    """Deactivate an account, reactivate it, or change its platform role.

    Two things this refuses, both of which are ways to lock the platform.

    You cannot act on yourself. An admin who deactivates their own account is
    signed out with no way back in, and one who demotes themselves cannot
    undo it -- and neither is ever what was meant, because the account being
    offboarded is somebody else's.

    You cannot remove the last admin. Deactivating or demoting the only
    remaining one leaves an install nobody can administer: no new accounts, no
    role changes, and no way to appoint a replacement. Both paths are checked
    because demoting is the one that does not look destructive.
    """
    user = _get_user_or_404(db, user_id)
    if user.id == actor.id:
        raise BadRequestError(
            "You cannot change your own account here. Ask another admin to do it."
        )

    fields = payload.model_dump(exclude_unset=True)
    deactivating = fields.get("is_active") is False
    demoting = "role" in fields and fields["role"] not in (None, "admin")

    if (deactivating or demoting) and user.role == "admin" and user.is_active:
        if _other_active_admins(db, user.id) == 0:
            raise ConflictError(
                "This is the only active admin. Promote another admin before "
                "changing this account, or the platform is left with nobody "
                "who can administer it."
            )

    if "is_active" in fields and fields["is_active"] is not None:
        user.is_active = fields["is_active"]
    if "role" in fields and fields["role"] is not None:
        user.role = fields["role"]

    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: uuid.UUID, actor: UserRead) -> None:
    """Remove an account outright.

    Deactivation is the better answer almost every time, and this refuses the
    cases where deleting would destroy something deactivation would not.

    The important one is ownership. `projects.owner_user_id` is `ON DELETE SET
    NULL`, and a project with a null owner is not a project with no owner -- it
    is one that `project_role` can never return a role for, so it becomes
    invisible to every user including admins, with its datasets and runs still
    in the database. Refusing here, and saying how many projects are in the
    way, keeps that from happening quietly.
    """
    user = _get_user_or_404(db, user_id)
    if user.id == actor.id:
        raise BadRequestError("You cannot delete your own account.")

    if user.role == "admin" and user.is_active and _other_active_admins(db, user.id) == 0:
        raise ConflictError(
            "This is the only active admin. Promote another admin before "
            "deleting this account."
        )

    owned = owned_project_count(db, user.id)
    if owned:
        raise ConflictError(
            f"{user.username} still owns {owned} project(s). Deleting the account "
            f"would leave them with no owner, which hides them from everyone "
            f"while their data stays in the database. Deactivate the account "
            f"instead, or move the projects to another owner first."
        )

    db.delete(user)
    db.commit()


def get_preferences(db: Session, user_id: uuid.UUID) -> PreferencesRead:
    """This person's interface settings, or the defaults if they have none.

    Absent preferences are not an error: most people never open the settings
    page, and "system theme, comfortable density" is the right answer for them.
    """
    row = db.scalar(select(UserPreference).where(UserPreference.user_id == user_id))
    if row is None:
        return PreferencesRead()
    return PreferencesRead.model_validate(row)


def set_preferences(
    db: Session, user_id: uuid.UUID, payload: PreferencesUpdate
) -> PreferencesRead:
    """Apply a partial update, creating the row on first use.

    Only fields the caller actually sent are touched -- a client saving the
    theme must not silently reset the density to its default.
    """
    row = db.scalar(select(UserPreference).where(UserPreference.user_id == user_id))
    if row is None:
        row = UserPreference(user_id=user_id)
        db.add(row)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return PreferencesRead.model_validate(row)
