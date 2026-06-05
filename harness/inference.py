from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


DEFAULT_ENDPOINT = "https://api.streamvc.live/v1/chat/completions"
DEFAULT_MODEL = "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
DEFAULT_PROVIDER = "air5"


@dataclass(frozen=True)
class InferenceConfig:
    endpoint: str = DEFAULT_ENDPOINT
    model: str = DEFAULT_MODEL
    provider: str = DEFAULT_PROVIDER
    temperature: float = 0.7
    top_p: float = 0.95
    n: int = 8
    timeout_s: float = 60.0
    max_retries: int = 3
    # Sleep this many seconds between successive single-completion calls
    # inside one fanned-out batch. Prevents per-minute burst throttles from
    # firing on a tight loop. Zero disables.
    inter_call_sleep_s: float = 0.5
    # Cap on 429-burst backoff. Quota_exhausted never retries; this only
    # applies to transient burst throttling.
    burst_backoff_cap_s: float = 30.0


class InferenceError(RuntimeError):
    """Generic inference failure. Carries a short stable `kind` for logging
    so attempt rows can be filtered by failure mode."""

    kind: str = "inference_error"

    def __init__(self, message: str, kind: str | None = None) -> None:
        super().__init__(message)
        if kind:
            self.kind = kind


class AuthError(InferenceError):
    kind = "auth_failed"


class QuotaExhaustedError(InferenceError):
    """Daily / monthly quota is gone. Retrying within this run is futile.
    Surfaces immediately and stops any in-flight fan-out batch."""

    kind = "quota_exhausted"

    def __init__(self, message: str, reset_unix: int | None = None) -> None:
        super().__init__(message)
        self.reset_unix = reset_unix


class BurstThrottledError(InferenceError):
    """Per-minute / per-second burst throttle. Retryable with backoff."""

    kind = "burst_throttled"


class ProviderUnreachableError(InferenceError):
    kind = "provider_unreachable"


class MacProviderClient:
    def __init__(self, api_key: str, config: InferenceConfig | None = None, demo_token: str = ""):
        # When both credentials are set, the long-lived API key wins over the
        # 24h demo token. Batch workloads (the canary, the 10k run) need the
        # API key's quota class; the demo token is for one-off probes.
        # Operators can drop an API key into .env without removing the demo
        # token line; the key implicitly retires the token.
        self.api_key = api_key
        self.demo_token = demo_token
        self.config = config or InferenceConfig()
        if not self.api_key and not self.demo_token:
            raise InferenceError(
                "no credential: set MACPROVIDER_API_KEY or MACPROVIDER_DEMO_TOKEN",
                kind="no_credential",
            )

    def complete(self, messages: list[dict[str, str]]) -> list[str]:
        # The MacProvider gateway currently rejects n>1 with
        # {"code":"n_must_be_1"}. Fan a requested batch out into N sequential
        # n=1 calls so the loop's diversity comes from temperature/top_p
        # sampling per call. Space the calls so per-minute burst throttles
        # don't fire on a tight loop.
        #
        # On QuotaExhausted (daily budget gone): stop the fan-out immediately
        # and raise — no point hammering further. On other transient errors:
        # continue so one bad call doesn't waste an otherwise productive
        # batch.
        responses: list[str] = []
        errors: list[InferenceError] = []
        n = max(1, int(self.config.n))
        for i in range(n):
            if i > 0 and self.config.inter_call_sleep_s > 0:
                time.sleep(self.config.inter_call_sleep_s)
            try:
                responses.extend(self._complete_one(messages))
            except QuotaExhaustedError as exc:
                # Daily budget gone — bail the whole batch
                errors.append(exc)
                break
            except AuthError as exc:
                # Bad credential won't get better on the next call
                errors.append(exc)
                break
            except InferenceError as exc:
                errors.append(exc)
        if responses:
            return responses
        if errors:
            raise errors[-1]
        raise InferenceError("no responses produced", kind="empty_batch")

    def _complete_one(self, messages: list[dict[str, str]]) -> list[str]:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "n": 1,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-MacProvider-Provider": self.config.provider,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            headers["X-Demo-Token"] = self.demo_token

        for attempt in range(self.config.max_retries + 1):
            req = urllib.request.Request(self.config.endpoint, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.config.timeout_s) as resp:
                    raw = resp.read()
                return parse_chat_response(raw)
            except urllib.error.HTTPError as exc:
                if exc.code in {401, 403}:
                    raise AuthError(f"authentication failed (http {exc.code})") from exc
                if exc.code == 429:
                    kind, retry_after, reset_unix = _classify_429(exc)
                    if kind == "quota_exhausted":
                        raise QuotaExhaustedError(
                            "daily quota exhausted; swap to API key or wait for reset",
                            reset_unix=reset_unix,
                        ) from exc
                    # burst throttle — respect Retry-After if present
                    sleep_s = retry_after if retry_after is not None else min(2**attempt, self.config.burst_backoff_cap_s)
                    if attempt >= self.config.max_retries:
                        raise BurstThrottledError(
                            f"burst throttled after {attempt + 1} attempts"
                        ) from exc
                    time.sleep(sleep_s)
                    continue
                if 500 <= exc.code < 600 and attempt < self.config.max_retries:
                    time.sleep(min(2**attempt, 30))
                    continue
                raise InferenceError(f"macprovider http {exc.code}", kind=f"http_{exc.code}") from exc
            except (TimeoutError, urllib.error.URLError) as exc:
                if attempt < self.config.max_retries:
                    time.sleep(min(2**attempt, 30))
                    continue
                raise ProviderUnreachableError("provider offline or timed out") from exc
        # Should be unreachable — every code path above either returns or raises.
        # Defensive raise so silent fallthrough is impossible.
        raise InferenceError("inference retries exhausted", kind="retries_exhausted")


def _classify_429(exc: urllib.error.HTTPError) -> tuple[str, float | None, int | None]:
    """Pull `error.code` out of the body and the rate-limit headers.
    Returns (kind, retry_after_seconds_or_None, ratelimit_reset_unix_or_None)."""
    kind = "burst"
    retry_after_s: float | None = None
    reset_unix: int | None = None
    ra_header = exc.headers.get("Retry-After")
    if ra_header:
        try:
            retry_after_s = float(ra_header)
        except ValueError:
            retry_after_s = None
    reset_header = exc.headers.get("X-Ratelimit-Reset")
    if reset_header:
        try:
            reset_unix = int(float(reset_header))
        except ValueError:
            reset_unix = None
    try:
        body_bytes = exc.read()
        body = json.loads(body_bytes) if body_bytes else {}
        err = body.get("error", {}) if isinstance(body, dict) else {}
        code = (err.get("code") or "").lower()
        if "quota" in code:
            kind = "quota_exhausted"
        elif "rate" in code or "burst" in code:
            kind = "burst"
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return kind, retry_after_s, reset_unix


def parse_chat_response(raw: bytes) -> list[str]:
    try:
        data = json.loads(raw)
        choices = data["choices"]
        return [choice["message"]["content"] for choice in choices]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise InferenceError("malformed chat completion response", kind="malformed_response") from exc
