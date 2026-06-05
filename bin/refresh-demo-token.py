#!/usr/bin/env python3
"""Refresh the 24h MacProvider demo token and update .env in place.

Usage:
    bin/refresh-demo-token.py                # update .env at repo root
    bin/refresh-demo-token.py --dry-run      # print the token, do not write

The demo session endpoint is anonymous but rate-limited per source IP per
hour (see phase5-gateway/internal/router/server.go handleDemoSession). If
this script returns 429, wait an hour or supply a long-lived API key via
MACPROVIDER_API_KEY in .env instead.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_URL = "https://api.streamvc.live/auth/demo-session"
REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"


def issue_token(url: str, timeout_s: float) -> tuple[str, str]:
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"demo-session HTTP {exc.code}: {detail}") from exc
    token = payload.get("demo_token")
    expires = payload.get("expires_at", "")
    if not token:
        raise SystemExit(f"demo-session returned no token: {payload}")
    return token, expires


def update_env(env_path: Path, token: str, expires: str) -> None:
    line = f"MACPROVIDER_DEMO_TOKEN={token}"
    if env_path.exists():
        text = env_path.read_text()
        if re.search(r"^MACPROVIDER_DEMO_TOKEN=.*$", text, flags=re.MULTILINE):
            text = re.sub(
                r"^MACPROVIDER_DEMO_TOKEN=.*$",
                line,
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            if not text.endswith("\n"):
                text += "\n"
            text += f"\n# refreshed; expires {expires}\n{line}\n"
    else:
        text = f"# arm64golf demo token; expires {expires}\n{line}\n"
    env_path.write_text(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--timeout-s", type=float, default=15.0)
    parser.add_argument("--env-path", default=str(ENV_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token, expires = issue_token(args.url, args.timeout_s)
    print(json.dumps({"expires_at": expires, "token_prefix": token[:24] + "..."}, indent=2))
    if args.dry_run:
        return 0
    update_env(Path(args.env_path), token, expires)
    print(f"updated {args.env_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
