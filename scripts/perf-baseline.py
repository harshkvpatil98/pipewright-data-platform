#!/usr/bin/env python3
"""A dependency-free performance baseline for the hot read endpoints.

Locust and k6 are great, but a baseline you can run with nothing but the Python
standard library is one that actually gets run -- in CI, on a laptop, against a
staging box -- without installing anything. This logs in once, then fires a
fixed number of requests at each endpoint across a small thread pool and reports
p50/p95/max latency and requests-per-second.

    PERF_BASE_URL=http://localhost:8000 PERF_USERNAME=admin PERF_PASSWORD=… \
      python scripts/perf-baseline.py --requests 200 --concurrency 8

Exit code is non-zero if any endpoint's p95 exceeds --budget-ms, so it can gate
a CI job. Reads only; it never mutates state.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

#: p95 budgets in milliseconds, enforced with --budgets (CI does, A7 X7). Set
#: for a shared CI runner with the workers idle: loose enough not to fail on a
#: noisy neighbour, tight enough that a query that stops using its index, or
#: a page that starts loading every row, fails the build. /status fans out to
#: every service and is scraped, not clicked, so its budget is the widest.
BUDGETS_MS = {
    "health": 150,
    "status": 2500,
    "metrics": 400,
    "auth/me": 250,
    "sso/status": 150,
    "projects": 1000,
    "runs": 600,
    "datasets": 800,
    "notifications": 500,
    "people": 250,
}

# (label, method, path). All reads; the login below supplies the token.
ENDPOINTS = [
    ("health", "GET", "/api/v1/health/live"),
    ("status", "GET", "/api/v1/status"),
    ("metrics", "GET", "/metrics"),
    ("auth/me", "GET", "/api/v1/auth/me"),
    ("sso/status", "GET", "/api/v1/auth/sso/status"),
    ("projects", "GET", "/api/v1/projects"),
    ("runs", "GET", "/api/v1/runs?limit=50"),
    ("datasets", "GET", "/api/v1/datasets?limit=50"),
    ("notifications", "GET", "/api/v1/notifications"),
    ("people", "GET", "/api/v1/auth/users"),
]


def _login(base_url: str, username: str, password: str) -> str:
    body = json.dumps({"username": username, "password": password}).encode()
    req = urllib.request.Request(
        f"{base_url}/api/v1/auth/login", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        payload = json.load(response)
    token = payload.get("access_token")
    if not token:
        raise SystemExit(
            "Login did not return a token (is MFA on for this user? use a service account)."
        )
    return token


def _time_one(base_url: str, method: str, path: str, token: str) -> float | None:
    req = urllib.request.Request(f"{base_url}{path}", method=method)
    req.add_header("Authorization", f"Bearer {token}")
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        # 4xx/5xx still took time and still count as latency; note failures too.
        exc.read()
        if exc.code >= 500:
            return None
    except Exception:
        return None
    return (time.perf_counter() - start) * 1000.0


def _pctl(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return ordered[index]


def _run_endpoint(base_url, method, path, token, requests, concurrency) -> dict:
    latencies: list[float] = []
    failures = 0
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(_time_one, base_url, method, path, token) for _ in range(requests)
        ]
        for future in futures:
            result = future.result()
            if result is None:
                failures += 1
            else:
                latencies.append(result)
    wall = time.perf_counter() - started
    return {
        "p50": _pctl(latencies, 0.50),
        "p95": _pctl(latencies, 0.95),
        "max": max(latencies) if latencies else 0.0,
        "rps": (len(latencies) / wall) if wall > 0 else 0.0,
        "failures": failures,
        "ok": len(latencies),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Baseline the hot read endpoints.")
    parser.add_argument("--base-url", default=os.environ.get("PERF_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--username", default=os.environ.get("PERF_USERNAME", "platform-admin"))
    parser.add_argument("--password", default=os.environ.get("PERF_PASSWORD", ""))
    parser.add_argument("--requests", type=int, default=200, help="Requests per endpoint.")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--budget-ms", type=float, default=0.0, help="Fail if any p95 exceeds this.")
    parser.add_argument(
        "--budgets", action="store_true",
        help="Fail if an endpoint's p95 passes its own budget (BUDGETS_MS) or any request fails.",
    )
    parser.add_argument(
        "--seed", type=int, default=0,
        help="Create this many demo projects first, so the lists have something to list.",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    token = _login(base_url, args.username, args.password)
    for _ in range(args.seed):
        req = urllib.request.Request(f"{base_url}/api/v1/projects/demo", method="POST", data=b"")
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=120) as response:
            response.read()
    if args.seed:
        print(f"Seeded {args.seed} demo project{'s' if args.seed != 1 else ''}.")

    print(f"Baseline: {args.requests} req x {args.concurrency} conc against {base_url}\n")
    header = f"{'endpoint':<16}{'p50 ms':>9}{'p95 ms':>9}{'max ms':>9}{'req/s':>9}{'fail':>7}"
    print(header)
    print("-" * len(header))

    breached = []
    for label, method, path in ENDPOINTS:
        stats = _run_endpoint(base_url, method, path, token, args.requests, args.concurrency)
        print(
            f"{label:<16}{stats['p50']:>9.1f}{stats['p95']:>9.1f}"
            f"{stats['max']:>9.1f}{stats['rps']:>9.1f}{stats['failures']:>7}"
        )
        if args.budget_ms and stats["p95"] > args.budget_ms:
            breached.append(f"{label} p95 {stats['p95']:.0f}ms > {args.budget_ms:.0f}ms")
        if args.budgets:
            budget = BUDGETS_MS.get(label)
            if budget is not None and stats["p95"] > budget:
                breached.append(f"{label} p95 {stats['p95']:.0f}ms > its budget of {budget}ms")
            if stats["failures"]:
                breached.append(f"{label}: {stats['failures']} requests failed")

    if breached:
        print("\nBUDGET EXCEEDED:")
        for line in breached:
            print(f"  - {line}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
