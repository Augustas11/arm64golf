#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


DEFAULT_MODELS_URL = "https://api.streamvc.live/v1/models"
TARGET_MODEL = "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
TARGET_PROVIDER = "air5"


def fetch_json(url: str, timeout_s: float, api_key: str = "", demo_token: str = "") -> Any:
    headers = {"Accept": "application/json"}
    # Demo token wins if both are set (explicit short-lived credential).
    if demo_token:
        headers["X-Demo-Token"] = demo_token
    elif api_key:
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


def operator_actions(model_ok: bool, provider_ok: bool, provider_candidates: list[str]) -> list[str]:
    actions: list[str] = []
    if not model_ok:
        actions.append(
            "Report to Augustas for air5-owner coordination: download/prewarm "
            "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit and configure phase3-binary "
            "to serve it for arm64golf."
        )
    if not provider_ok:
        actions.append(
            "Report to Augustas for air5-owner coordination: reconnect the provider or "
            "document the live provider id mapping; "
            f"expected one of: {', '.join(provider_candidates)}."
        )
    return actions


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether air5 is advertising the arm64golf coder model.")
    parser.add_argument("--url", default=DEFAULT_MODELS_URL)
    parser.add_argument("--model", default=TARGET_MODEL)
    parser.add_argument("--provider", default=TARGET_PROVIDER)
    parser.add_argument("--provider-alias", action="append", default=[])
    parser.add_argument("--api-key", default=os.environ.get("MACPROVIDER_API_KEY", ""))
    parser.add_argument("--demo-token", default=os.environ.get("MACPROVIDER_DEMO_TOKEN", ""))
    parser.add_argument("--timeout-s", type=float, default=10.0)
    args = parser.parse_args()

    try:
        payload = fetch_json(args.url, args.timeout_s, args.api_key, args.demo_token)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        print(f"models check failed: HTTP {exc.code} {detail}", file=sys.stderr)
        return 2
    except (TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"models check failed: {exc}", file=sys.stderr)
        return 2

    # The gateway's /v1/models response intentionally does NOT publish
    # provider IDs by name (privacy / anti-fingerprinting). It only exposes
    # provider_count and total_slots. So "provider_present" really means
    # "at least one provider is currently serving this model", confirmed via
    # the provider_count field on the matching model entry.
    model_entry = None
    for entry in payload.get("data", []) if isinstance(payload, dict) else []:
        if isinstance(entry, dict) and entry.get("id") == args.model:
            model_entry = entry
            break

    model_ok = model_entry is not None
    provider_count = int(model_entry.get("provider_count", 0)) if model_entry else 0
    total_slots = int(model_entry.get("total_slots", 0)) if model_entry else 0
    provider_ok = provider_count >= 1 and total_slots >= 1

    provider_candidates = [args.provider, *args.provider_alias]
    actions = operator_actions(model_ok, provider_ok, provider_candidates)

    print(
        json.dumps(
            {
                "url": args.url,
                "model": args.model,
                "model_present": model_ok,
                "provider": args.provider,
                "provider_aliases": args.provider_alias,
                "provider_present": provider_ok,
                "provider_count": provider_count,
                "total_slots": total_slots,
                "operator_actions": actions,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if model_ok and provider_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
