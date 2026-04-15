from __future__ import annotations

import argparse

from api_gateway.dependencies import SessionLocal
from api_gateway import metadata as _metadata  # noqa: F401
from service_auth.schemas import BootstrapUserRequest
from service_auth.service import create_user


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap a local platform user.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", default="admin")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        user = create_user(
            db,
            BootstrapUserRequest(username=args.username, password=args.password, role=args.role),
        )
    finally:
        db.close()

    print(f"Created user '{user.username}' with role '{user.role}'.")
