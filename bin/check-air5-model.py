#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


DEFAULT_MODELS_URL = "https://coordinator.streamvc.live/v1/models"
TARGET_MODEL = "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
TARGET_PROVIDER = "air5"


def fetch_json(url: str, timeout_s: float, api_key: str = "") -> Any:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read())


def flatten_strings(value: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(value, str):
        strings.append(value)
    elif isinstance(value, list):
        for item in value:
            strings.extend(flatten_strings(item))
    elif isinstance(value, dict):
        for item in value.values():
            strings.extend(flatten_strings(item))
    return strings


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether air5 is advertising the arm64golf coder model.")
    parser.add_argument("--url", default=DEFAULT_MODELS_URL)
    parser.add_argument("--model", default=TARGET_MODEL)
    parser.add_argument("--provider", default=TARGET_PROVIDER)
    parser.add_argument("--provider-alias", action="append", default=[])
    parser.add_argument("--api-key", default=os.environ.get("MACPROVIDER_API_KEY", ""))
    parser.add_argument("--timeout-s", type=float, default=10.0)
    args = parser.parse_args()

    try:
        payload = fetch_json(args.url, args.timeout_s, args.api_key)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        print(f"models check failed: HTTP {exc.code} {detail}", file=sys.stderr)
        return 2
    except (TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"models check failed: {exc}", file=sys.stderr)
        return 2

    strings = flatten_strings(payload)
    model_ok = args.model in strings
    provider_candidates = [args.provider, *args.provider_alias]
    provider_ok = any(provider in strings for provider in provider_candidates)

    print(
        json.dumps(
            {
                "url": args.url,
                "model": args.model,
                "model_present": model_ok,
                "provider": args.provider,
                "provider_aliases": args.provider_alias,
                "provider_present": provider_ok,
                "string_count": len(strings),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if model_ok and provider_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
