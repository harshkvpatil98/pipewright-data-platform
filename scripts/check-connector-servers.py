#!/usr/bin/env python
"""Fail if a database a tier-2 connector cites is not actually reachable.

`test_containers.py` skips servers it cannot reach, which is right for a
developer's laptop and wrong for CI: a skipped test is a green build, and a
green build is what the "◑ Tested" badge rests on. So CI checks separately that
the containers it declared are up, and says which one is not.

Run with no arguments. Reads the same environment variables the tests do.
"""

from __future__ import annotations

import os
import sys

#: Variable -> the connectors whose tier claim depends on it.
REQUIRED = {
    "CONNECTORS_TEST_POSTGRES_URL": ("postgresql",),
    "CONNECTORS_TEST_MYSQL_URL": ("mysql",),
    "CONNECTORS_TEST_MARIADB_URL": ("mariadb",),
}


def main() -> int:
    import sqlalchemy as sa

    problems: list[str] = []
    for variable, connectors in REQUIRED.items():
        url = os.environ.get(variable)
        named = ", ".join(connectors)
        if not url:
            problems.append(f"{variable} is not set, so {named} would be skipped.")
            continue
        engine = None
        try:
            engine = sa.create_engine(url, pool_pre_ping=False)
            with engine.connect() as connection:
                connection.execute(sa.text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - any failure is the answer
            problems.append(f"{variable} is set but unreachable ({exc.__class__.__name__}): {named}.")
        finally:
            if engine is not None:
                engine.dispose()

    if problems:
        print("Connector verification servers are not available:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nThese connectors claim tier 2, which means a container runs them on "
            "every merge. Either start the servers or lower the claim.",
            file=sys.stderr,
        )
        return 1

    print("All connector verification servers are reachable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
