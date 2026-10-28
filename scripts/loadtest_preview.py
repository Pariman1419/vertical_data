"""Read-only preview load probe. Credentials come ONLY from environment variables.

LOADTEST_USER, LOADTEST_PASSWORD required. LOADTEST_BASE_URL defaults to localhost:8017;
LOADTEST_WORKSPACE / LOADTEST_CONNECTION optionally select a workspace/connection, otherwise
the first available is used. No catalog/allowlist mutation, SQL argument or source DB access.
"""
import argparse
import concurrent.futures
import http.cookiejar
import json
import math
import os
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


def session(base, username, password):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    csrf = ""
    def request(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method,
            headers={"Content-Type": "application/json", "Origin": base, "X-CSRF-Token": csrf})
        try:
            with opener.open(req, timeout=15) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, None  # never print response bodies or credentials
    status, auth = request("POST", "/api/v2/auth/login", {"username": username, "password": password})
    if status != 200:
        raise RuntimeError("Load-test login failed (HTTP " + str(status) + ")")
    csrf = auth["csrf"]
    return request


def run(users, seconds, obj):
    if not 1 <= users <= 100 or not 1 <= seconds <= 3600:
        raise ValueError("users must be 1–100 and seconds 1–3600")
    base = os.environ.get("LOADTEST_BASE_URL", "http://127.0.0.1:8017").rstrip("/")
    if urllib.parse.urlsplit(base).scheme not in ("http", "https"):
        raise ValueError("HTTP(S) base URL required")
    username, password = os.environ.get("LOADTEST_USER"), os.environ.get("LOADTEST_PASSWORD")
    if not username or not password:
        raise ValueError("Set LOADTEST_USER and LOADTEST_PASSWORD in the environment")
    sessions = [session(base, username, password) for _ in range(users)]
    _, me = sessions[0]("GET", "/api/v2/auth/me")
    workspace = os.environ.get("LOADTEST_WORKSPACE") or me["workspaces"][0]["id"]
    _, connections = sessions[0]("GET", f"/api/v2/workspaces/{workspace}/connections")
    connection = os.environ.get("LOADTEST_CONNECTION") or connections[0]["id"]
    path = f"/api/v2/workspaces/{workspace}/connections/{connection}/preview"
    barrier = threading.Barrier(users + 1)
    deadline = 0
    def worker(request):
        barrier.wait()
        latencies, statuses = [], {}
        while time.monotonic() < deadline:
            start = time.perf_counter()
            try:
                status, _ = request("POST", path, {"object": obj, "limit": 100})
            except (OSError, ValueError):
                status = 0
            latencies.append((time.perf_counter() - start) * 1000)
            statuses[status] = statuses.get(status, 0) + 1
            # Avoid a hot 429 loop flooding the audit log; these remain explicit test requests.
            time.sleep(0.1 if status == 429 else 0.02)
        return latencies, statuses
    with concurrent.futures.ThreadPoolExecutor(max_workers=users) as executor:
        jobs = [executor.submit(worker, request) for request in sessions]
        deadline = time.monotonic() + seconds
        barrier.wait()
        outcomes = [job.result() for job in jobs]
    latencies, statuses = [], {}
    for values, counts in outcomes:
        latencies.extend(values)
        for status, count in counts.items():
            statuses[status] = statuses.get(status, 0) + count
    latencies.sort()
    result = {"users": users, "seconds": seconds, "object": obj, "requests": len(latencies),
              "p50_ms": round(statistics.median(latencies), 1),
              "p95_ms": round(latencies[math.ceil(len(latencies) * .95) - 1], 1),
              "busy_429": statuses.get(429, 0),
              "errors": sum(count for status, count in statuses.items() if status not in (200, 429)),
              "statuses": statuses}
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--object", required=True)
    args = parser.parse_args()
    try:
        result = run(args.users, args.seconds, args.object)
        raise SystemExit(1 if result["errors"] else 0)
    except (ValueError, RuntimeError, IndexError, KeyError, OSError):
        raise SystemExit("Load test could not start; check environment credentials, workspace/connection and connectivity.") from None
