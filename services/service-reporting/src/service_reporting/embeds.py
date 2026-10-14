"""Dashboards shown inside other sites (adoption-readiness A8, Y4).

An embed belongs to one dashboard and has its own signing secret. Its link is
a token signed with that secret (HS256, the JSON Web Token every language
has a library for) carrying the embed's id and an expiry, and optionally
filters fixed for whoever holds it:

    {"embed": "<embed id>", "exp": 1767225600, "filters": [{"column": "customer", "value": "C-17"}]}

Pipewright signs one such link when the embed is made, lasting as long as the
embed does. A partner's server can sign its own with the same secret: short
ones, made as each page loads, and with filters that show each of its
customers only their own rows. A viewer cannot change a signed link, so
cannot widen the filters or stretch the expiry. Turning the embed off stops
every link signed with it, whoever signed it.

Which sites may show the page in a frame is the web's setting,
`EMBED_ALLOWED_ORIGINS`, because the web serves the page.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_projects.contracts import ensure_owned_project
from shared_python.errors import ApplicationError, BadRequestError, NotFoundError
from shared_python.security.encryption import decrypt_secret_value, encrypt_secret_value

from service_reporting.aggregation import FILTER_OPERATORS
from service_reporting.delivery import web_base_url
from service_reporting.models import Dashboard, DashboardEmbed
from service_reporting.schemas import (
    DashboardEmbedCreate,
    DashboardEmbedListResponse,
    DashboardEmbedRead,
    FilterInput,
    PublicDashboardView,
)

#: How long an embed can last, in days, as the page offers it.
EMBED_DAYS = (1, 7, 30, 90, 365)
SECRET_PREFIX = "emb_"
#: Clocks on the partner's server and here may differ by this much.
LEEWAY_SECONDS = 30
MAX_FILTERS = 10

NOT_AVAILABLE = "This embedded dashboard is not available."


class EmbedExpired(ApplicationError):
    """The link ran out: 410, so the page can say so rather than "not found"."""

    status_code = 410


def new_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(32)


def sign(embed_id: uuid.UUID | str, secret: str, *, expires_at: datetime, filters: list[dict] | None = None) -> str:
    """A link token, as a partner's server would make one."""
    claims: dict[str, Any] = {"embed": str(embed_id), "exp": int(expires_at.timestamp())}
    if filters:
        claims["filters"] = filters
    return jwt.encode(claims, secret, algorithm="HS256")


def embed_url(token: str) -> str | None:
    base = web_base_url()
    return f"{base}/embed/{token}" if base else None


def _aware(moment: datetime) -> datetime:
    # SQLite hands back naive datetimes; they were written in UTC.
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _read(embed: DashboardEmbed, *, secret: str | None = None) -> DashboardEmbedRead:
    plain = decrypt_secret_value(embed.signing_secret)
    token = sign(embed.id, plain, expires_at=_aware(embed.expires_at))
    now = datetime.now(UTC)
    state = "off" if embed.revoked_at else ("expired" if _aware(embed.expires_at) <= now else "on")
    return DashboardEmbedRead(
        id=embed.id,
        dashboard_id=embed.dashboard_id,
        name=embed.name,
        state=state,
        token=token if state == "on" else None,
        url=embed_url(token) if state == "on" else None,
        signing_secret=secret,
        secret_hint=f"{SECRET_PREFIX}…{plain[-4:]}",
        expires_at=embed.expires_at,
        revoked_at=embed.revoked_at,
        last_opened_at=embed.last_opened_at,
        created_at=embed.created_at,
    )


def _dashboard(db: Session, project_id: uuid.UUID, dashboard_id: uuid.UUID) -> Dashboard:
    dashboard = db.scalar(select(Dashboard).where(Dashboard.id == dashboard_id, Dashboard.project_id == project_id))
    if dashboard is None:
        raise NotFoundError("Dashboard not found.")
    return dashboard


def list_embeds(
    db: Session, project_id: uuid.UUID, dashboard_id: uuid.UUID, current_user: UserRead
) -> DashboardEmbedListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    _dashboard(db, project_id, dashboard_id)
    rows = db.scalars(
        select(DashboardEmbed)
        .where(DashboardEmbed.dashboard_id == dashboard_id)
        .order_by(DashboardEmbed.created_at.desc())
    ).all()
    return DashboardEmbedListResponse(items=[_read(row) for row in rows])


def create_embed(
    db: Session, project_id: uuid.UUID, dashboard_id: uuid.UUID, payload: DashboardEmbedCreate, current_user: UserRead
) -> DashboardEmbedRead:
    """Made here; the secret is in this answer once and kept encrypted."""
    ensure_owned_project(db, project_id, current_user.id)
    _dashboard(db, project_id, dashboard_id)
    if payload.days not in EMBED_DAYS:
        raise BadRequestError(f"An embed can last {', '.join(str(days) for days in EMBED_DAYS)} days.")
    secret = new_secret()
    embed = DashboardEmbed(
        project_id=project_id,
        dashboard_id=dashboard_id,
        name=payload.name.strip(),
        signing_secret=encrypt_secret_value(secret),
        expires_at=datetime.now(UTC) + timedelta(days=payload.days),
        created_by_user_id=current_user.id,
    )
    db.add(embed)
    db.commit()
    db.refresh(embed)
    return _read(embed, secret=secret)


def revoke_embed(
    db: Session, project_id: uuid.UUID, dashboard_id: uuid.UUID, embed_id: uuid.UUID, current_user: UserRead
) -> DashboardEmbedRead:
    ensure_owned_project(db, project_id, current_user.id)
    embed = db.scalar(
        select(DashboardEmbed).where(
            DashboardEmbed.id == embed_id,
            DashboardEmbed.dashboard_id == dashboard_id,
            DashboardEmbed.project_id == project_id,
        )
    )
    if embed is None:
        raise NotFoundError("Embed not found.")
    if embed.revoked_at is None:
        embed.revoked_at = datetime.now(UTC)
        db.commit()
        db.refresh(embed)
    return _read(embed)


def open_embed(db: Session, *, token: str) -> tuple[Dashboard, list[FilterInput]]:
    """The dashboard a link shows, and the filters it fixes; or why not.

    The embed is found from the token's unverified claims, then the token is
    checked against that embed's own secret, HS256 only, so a token cannot
    choose its algorithm or sign itself with none.
    """
    try:
        claims = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256"])
        embed_id = uuid.UUID(str(claims.get("embed")))
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise NotFoundError(NOT_AVAILABLE) from exc
    embed = db.get(DashboardEmbed, embed_id)
    if embed is None or embed.revoked_at is not None:
        raise NotFoundError(NOT_AVAILABLE)
    try:
        claims = jwt.decode(
            token,
            decrypt_secret_value(embed.signing_secret),
            algorithms=["HS256"],
            options={"require": ["exp", "embed"]},
            leeway=LEEWAY_SECONDS,
        )
    except jwt.ExpiredSignatureError as exc:
        raise EmbedExpired("This link has run out.") from exc
    except jwt.PyJWTError as exc:
        raise NotFoundError(NOT_AVAILABLE) from exc
    if _aware(embed.expires_at) <= datetime.now(UTC):
        raise EmbedExpired("This link has run out.")

    raw = claims.get("filters") or []
    if not isinstance(raw, list) or len(raw) > MAX_FILTERS:
        raise BadRequestError(f"A link can fix up to {MAX_FILTERS} filters, as a list.")
    try:
        filters = [FilterInput.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise BadRequestError("The link's filters could not be read. Each needs a column, and a value.") from exc
    unknown = sorted({item.operator for item in filters} - set(FILTER_OPERATORS))
    if unknown:
        raise BadRequestError(f"The link's filters use {', '.join(unknown)}. Try: {', '.join(FILTER_OPERATORS)}.")

    dashboard = db.get(Dashboard, embed.dashboard_id)
    if dashboard is None:
        raise NotFoundError(NOT_AVAILABLE)
    embed.last_opened_at = datetime.now(UTC)
    db.commit()
    return dashboard, filters


def embedded_dashboard(db: Session, *, token: str, storage_backend) -> PublicDashboardView:
    from service_reporting.service import public_dashboard_view

    dashboard, filters = open_embed(db, token=token)
    return public_dashboard_view(db, dashboard, storage_backend, fixed_filters=filters)
