"""CLI: deactivate directory-managed accounts absent from a directory snapshot.

Feed it the usernames still in the directory (one per line, from a file or
stdin) and it deactivates the SSO-provisioned accounts that are no longer among
them -- the offboarding half of SCIM, runnable from cron or a CI job.

    directory-export | scim-sync --stdin
    scim-sync --file present-users.txt --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys

import api_gateway.metadata  # noqa: F401  -- registers every model mapping
from api_gateway.dependencies import SessionLocal
from api_gateway.scim_sync import deactivate_absent_sso_users


def _read_usernames(args) -> set[str]:
    if args.file:
        with open(args.file, encoding="utf-8") as handle:
            return {line.strip() for line in handle if line.strip()}
    if args.stdin:
        return {line.strip() for line in sys.stdin if line.strip()}
    raise SystemExit("Provide --file <path> or --stdin with the directory's usernames.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Deactivate SSO users absent from the directory.")
    parser.add_argument("--file", help="File of present usernames, one per line.")
    parser.add_argument("--stdin", action="store_true", help="Read present usernames from stdin.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would change without changing it."
    )
    args = parser.parse_args()

    present = _read_usernames(args)
    db = SessionLocal()
    try:
        summary = deactivate_absent_sso_users(db, present_usernames=present, dry_run=args.dry_run)
    finally:
        db.close()
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
