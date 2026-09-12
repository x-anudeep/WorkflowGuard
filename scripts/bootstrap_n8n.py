#!/usr/bin/env python3
"""Make a fresh n8n instance usable by the integration suite, without the UI.

n8n's public API needs an owner account and an API key, both normally created by clicking
through the editor. CI has no one to click, so this does it over the internal REST API:

    python scripts/bootstrap_n8n.py --base-url http://localhost:5678

It prints ``N8N_API_KEY=<key>`` on stdout, suitable for appending to ``$GITHUB_ENV`` or eval-ing
in a shell. Everything else goes to stderr so the output stays machine-readable.

Two things that cost time to discover, worth keeping written down:

* The key must carry ``workflow:activate``. Without it, publishing fails with a bare
  ``403 Forbidden`` and no indication of which scope is missing.
* ``POST /workflows/{id}/activate`` is deprecated in n8n 2.x; publishing is what makes a
  workflow's production webhook live.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

#: Everything a test run does: create a workflow, publish it, read the execution, clean up.
SCOPES = [
    "workflow:create",
    "workflow:read",
    "workflow:update",
    "workflow:delete",
    "workflow:list",
    "workflow:activate",
    "workflow:deactivate",
    "execution:read",
    "execution:list",
    "execution:delete",
]


def log(message: str) -> None:
    print(message, file=sys.stderr)


def request(
    base_url: str, method: str, path: str, body: dict | None = None, cookie: str | None = None
) -> tuple[int, dict, str]:
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(
        base_url + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode()
            payload = json.loads(raw) if raw.strip().startswith("{") else {}
            return response.status, payload, response.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        payload = json.loads(raw) if raw.strip().startswith("{") else {}
        return exc.code, payload, ""


def wait_until_ready(base_url: str, timeout: float) -> None:
    """Wait for the REST API, not just the health endpoint.

    `/healthz` starts answering well before `/rest/*` is mounted, so polling it alone makes a
    CI run race n8n's startup and get a 404 from owner setup - which looks exactly like "an
    owner already exists" and sends the script down the wrong path.
    """
    deadline = time.monotonic() + timeout
    last = "no response"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/rest/settings", timeout=5) as response:
                if response.status == 200:
                    log(f"n8n REST API is ready at {base_url}")
                    return
                last = f"HTTP {response.status}"
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
        except (urllib.error.URLError, OSError) as exc:
            last = str(exc)
        time.sleep(2)
    raise SystemExit(f"n8n REST API not ready at {base_url} within {timeout:g}s (last: {last})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:5678")
    parser.add_argument("--email", default="ci@workflowguard.local")
    parser.add_argument("--password", default="WorkflowGuardCI1")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    wait_until_ready(args.base_url, args.timeout)

    # A fresh instance needs an owner; a reused volume already has one, so fall back to logging
    # in rather than failing. Both paths just need a session cookie.
    status, _, cookie = request(
        args.base_url,
        "POST",
        "/rest/owner/setup",
        {
            "email": args.email,
            "firstName": "WorkflowGuard",
            "lastName": "CI",
            "password": args.password,
        },
    )
    if status == 200:
        log("created the owner account")
    else:
        log(f"owner setup returned {status}; trying to log in instead")
        status, _, cookie = request(
            args.base_url,
            "POST",
            "/rest/login",
            {"emailOrLdapLoginId": args.email, "password": args.password},
        )
        if status != 200:
            raise SystemExit(f"could not create or log in as the owner (HTTP {status})")
        log("logged in as the existing owner")

    if not cookie:
        raise SystemExit("n8n did not return a session cookie")

    status, payload, _ = request(
        args.base_url,
        "POST",
        "/rest/api-keys",
        {"label": f"workflowguard-ci-{int(time.time())}", "expiresAt": None, "scopes": SCOPES},
        cookie=cookie.split(";", 1)[0],
    )
    if status != 200:
        raise SystemExit(f"could not create an API key (HTTP {status}): {payload}")

    key = (payload.get("data") or {}).get("rawApiKey")
    if not key:
        raise SystemExit("n8n created a key but did not return it; it is only shown once")

    log(f"minted an API key with {len(SCOPES)} scopes")
    print(f"N8N_API_KEY={key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
