#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ENDPOINT = "https://api.streamvc.live/v1/chat/completions"
EXPECTED_MODEL = "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
EXPECTED_PROVIDER = "air5"
EXPECTED_TEMPERATURE = 0.7
EXPECTED_TOP_P = 0.95
EXPECTED_N = 8

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness import inference  # noqa: E402


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def header_value(headers: dict[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return ""


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"choices":[{"message":{"content":"cmp x0, x1\\n"}}]}'


def validate_defaults(errors: list[str]) -> None:
    config = inference.InferenceConfig()
    require(inference.DEFAULT_ENDPOINT == EXPECTED_ENDPOINT, "DEFAULT_ENDPOINT must be MacProvider chat completions", errors)
    require(inference.DEFAULT_MODEL == EXPECTED_MODEL, "DEFAULT_MODEL must be Qwen2.5-Coder-7B-Instruct-4bit", errors)
    require(inference.DEFAULT_PROVIDER == EXPECTED_PROVIDER, "DEFAULT_PROVIDER must be air5", errors)
    require(config.endpoint == EXPECTED_ENDPOINT, "InferenceConfig.endpoint must default to MacProvider", errors)
    require(config.model == EXPECTED_MODEL, "InferenceConfig.model must default to coder model", errors)
    require(config.provider == EXPECTED_PROVIDER, "InferenceConfig.provider must default to air5", errors)
    require(config.temperature == EXPECTED_TEMPERATURE, "InferenceConfig.temperature must default to 0.7", errors)
    require(config.top_p == EXPECTED_TOP_P, "InferenceConfig.top_p must default to 0.95", errors)
    require(config.n == EXPECTED_N, "InferenceConfig.n must default to 8", errors)


def validate_request_shape(errors: list[str]) -> None:
    # The gateway rejects n>1 with HTTP 400 {"code":"n_must_be_1"}, so the
    # client fans config.n out into config.n separate single-completion calls.
    # Each call sends n=1 in the body; the diversity comes from per-call
    # temperature/top_p sampling. The validator asserts the new contract.
    captured: list[dict[str, Any]] = []
    original_urlopen = inference.urllib.request.urlopen
    original_sleep = inference.time.sleep

    def fake_urlopen(req, timeout: float):
        captured.append(
            {
                "url": req.full_url,
                "method": req.get_method(),
                "headers": dict(req.header_items()),
                "body": json.loads(req.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return FakeResponse()

    inference.urllib.request.urlopen = fake_urlopen
    inference.time.sleep = lambda seconds: None
    try:
        client = inference.MacProviderClient("test-key")
        responses = client.complete([{"role": "user", "content": "candidate?"}])
    finally:
        inference.urllib.request.urlopen = original_urlopen
        inference.time.sleep = original_sleep

    require(
        responses == ["cmp x0, x1\n"] * EXPECTED_N,
        f"client must fan config.n={EXPECTED_N} calls and concatenate their parsed contents",
        errors,
    )
    require(
        len(captured) == EXPECTED_N,
        f"client must issue exactly config.n={EXPECTED_N} HTTP requests",
        errors,
    )
    if not captured:
        return
    first = captured[0]
    require(first.get("url") == EXPECTED_ENDPOINT, "client must POST to the pinned MacProvider endpoint", errors)
    require(first.get("method") == "POST", "client must use POST", errors)
    headers = first.get("headers", {})
    require(isinstance(headers, dict), "captured headers must be a dict", errors)
    if isinstance(headers, dict):
        require(header_value(headers, "Content-Type") == "application/json", "client must send JSON content type", errors)
        require(header_value(headers, "Authorization") == "Bearer test-key", "client must send bearer auth", errors)
        require(
            header_value(headers, "X-MacProvider-Provider") == EXPECTED_PROVIDER,
            "client must pin X-MacProvider-Provider to air5",
            errors,
        )
    body = first.get("body")
    require(isinstance(body, dict), "captured request body must be a JSON object", errors)
    if isinstance(body, dict):
        require(body.get("model") == EXPECTED_MODEL, "request body model must be the pinned coder model", errors)
        require(body.get("temperature") == EXPECTED_TEMPERATURE, "request body temperature must be 0.7", errors)
        require(body.get("top_p") == EXPECTED_TOP_P, "request body top_p must be 0.95", errors)
        require(
            body.get("n") == 1,
            "request body n must be 1 (gateway rejects n>1; client fans out client-side)",
            errors,
        )
        require(body.get("messages") == [{"role": "user", "content": "candidate?"}], "request body messages must pass through", errors)


def validate_no_auth_retry(errors: list[str]) -> None:
    # 401/403 must surface as AuthError immediately, with no retry. The fan
    # out must also bail the whole batch on AuthError — burning N requests
    # against a known-bad key is pointless. So attempts must equal 1 even
    # though config.n=8 by default.
    original_urlopen = inference.urllib.request.urlopen
    original_sleep = inference.time.sleep
    attempts = 0

    def fake_urlopen(req, timeout: float):
        nonlocal attempts
        attempts += 1
        raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", {}, None)

    inference.urllib.request.urlopen = fake_urlopen
    inference.time.sleep = lambda seconds: None
    try:
        try:
            inference.MacProviderClient("bad-key").complete([{"role": "user", "content": "candidate?"}])
        except inference.AuthError as exc:
            require(
                "authentication failed" in str(exc),
                "401 must surface as AuthError with 'authentication failed' in the message",
                errors,
            )
            require(
                getattr(exc, "kind", "") == "auth_failed",
                "AuthError must carry kind='auth_failed' for attempt-log filtering",
                errors,
            )
        except inference.InferenceError as exc:
            errors.append(f"401 must raise AuthError (got {type(exc).__name__}: {exc})")
        else:
            errors.append("401 response must raise AuthError")
    finally:
        inference.urllib.request.urlopen = original_urlopen
        inference.time.sleep = original_sleep

    require(attempts == 1, "authentication failures must not be retried (no fan-out, no per-call retry)", errors)


def validate() -> list[str]:
    errors: list[str] = []
    validate_defaults(errors)
    validate_request_shape(errors)
    validate_no_auth_retry(errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate arm64golf MacProvider inference request configuration.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable validation result.")
    args = parser.parse_args()

    errors = validate()
    payload = {"ok": not errors, "errors": errors}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif errors:
        for error in errors:
            print(error, file=sys.stderr)
    else:
        print("ok")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
