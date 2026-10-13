"""Rate limits on the addresses anyone can call (adoption-readiness A7, X5).

Sign-in, one-time codes, public dashboards and inbound webhooks answer
without a session, so nothing else stops a script from calling them as fast
as it likes: guessing passwords, or loading a shared dashboard in a loop.
Each is limited per caller in fixed windows.

The counts live in the database, not in a gateway's memory, so several
gateways share one limit; a counter in each would multiply it by the number
of gateways. One atomic upsert per request keeps that cheap. Old windows are
removed by the schedule ticker (`forget_old_windows`).

`RATE_LIMITS_ENABLED=false` turns the limits off, for a load test.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, Integer, String, delete
from sqlalchemy.orm import Mapped, Session, mapped_column

from shared_python.db import Base
from shared_python.errors import TooManyRequestsError


class RateLimitWindow(Base):
    """How many times one caller has hit one limit in one window."""

    __tablename__ = "rate_limit_windows"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


@dataclass(frozen=True)
class Limit:
    """At most `count` requests per `seconds`, per caller. `what` finishes "Too many …"."""

    name: str
    count: int
    seconds: int
    what: str


#: A password is tried at most 10 times in 5 minutes for one account from one
#: address, and an address signs in at most 60 times a minute whatever the
#: account (the second stops one address trying many accounts).
SIGN_IN_PER_ACCOUNT = Limit("sign-in-account", 10, 300, "sign-in attempts for this account")
SIGN_IN_PER_ADDRESS = Limit("sign-in-address", 60, 60, "sign-in attempts from this address")
#: Activation and reset codes, and second-factor codes.
CODES_PER_ADDRESS = Limit("codes-address", 10, 300, "codes tried from this address")
#: A shared dashboard, opened from one address.
PUBLIC_DASHBOARD_PER_ADDRESS = Limit("public-dashboard", 120, 60, "requests for shared dashboards from this address")
#: One webhook's events.
WEBHOOK_PER_TOKEN = Limit("webhook", 600, 60, "events sent to this webhook")

LIMITS = (SIGN_IN_PER_ACCOUNT, SIGN_IN_PER_ADDRESS, CODES_PER_ADDRESS, PUBLIC_DASHBOARD_PER_ADDRESS, WEBHOOK_PER_TOKEN)


def enabled() -> bool:
    return os.environ.get("RATE_LIMITS_ENABLED", "true").strip().lower() not in ("false", "0", "no", "off")


def _wait_in_words(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} second{'' if seconds == 1 else 's'}"
    minutes = -(-seconds // 60)
    return f"{minutes} minute{'' if minutes == 1 else 's'}"


def hit(db: Session, limit: Limit, caller: str, *, now: datetime | None = None) -> None:
    """Count one request from `caller`; refuse it, with when to retry, past the limit."""
    if not enabled():
        return
    moment = now or datetime.now(UTC)
    epoch = int(moment.timestamp())
    start_epoch = epoch - epoch % limit.seconds
    window_start = datetime.fromtimestamp(start_epoch, UTC)
    key = f"{limit.name}:{caller}"[:255]

    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    statement = (
        insert(RateLimitWindow)
        .values(key=key, window_start=window_start, hits=1)
        .on_conflict_do_update(
            index_elements=[RateLimitWindow.key, RateLimitWindow.window_start],
            set_={"hits": RateLimitWindow.hits + 1},
        )
        .returning(RateLimitWindow.hits)
    )
    hits = db.execute(statement).scalar_one()
    # Committed now: the count has to stand even when the request it belongs
    # to then fails (a wrong password rolls its own work back).
    db.commit()
    if hits > limit.count:
        retry_after = start_epoch + limit.seconds - epoch
        raise TooManyRequestsError(
            f"Too many {limit.what}. Try again in {_wait_in_words(retry_after)}.",
            retry_after=retry_after,
        )


def forget_old_windows(db: Session, *, now: datetime | None = None) -> int:
    """Remove windows that ended over a day ago. Returns how many."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=1)
    removed = db.execute(delete(RateLimitWindow).where(RateLimitWindow.window_start < cutoff)).rowcount or 0
    db.commit()
    return removed
