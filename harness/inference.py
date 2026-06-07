from __future__ import annotations

import json
import http.client
import re
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
    # Sort3-arm64 reference is 18 instructions; verified candidates have been
    # ≤18. 256 tokens is ~4× upper bound, leaving headroom for the model's
    # preamble/postamble noise without enabling rambling 1000+ token
    # completions that previously blew through the 10s gateway header
    # timeout. SSE streaming now keeps bytes flowing under the standard
    # gateway timeout; the 60s client cap is a fallback rather than a
    # load-bearing knob.
    max_tokens: int = 256
    # Sleep this many seconds between successive single-completion calls
    # inside one fanned-out batch. Prevents per-minute burst throttles from
    # firing on a tight loop. Zero disables.
    inter_call_sleep_s: float = 0.5
    # Cap on 429-burst backoff. Quota_exhausted never retries; this only
    # applies to transient burst throttling.
    burst_backoff_cap_s: float = 30.0
    stream_total_timeout_s: float = 60.0
    stream_idle_timeout_s: float = 10.0
    stream_max_bytes: int = 4 * 1024 * 1024
    stream_max_line_bytes: int = 64 * 1024


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
            "max_tokens": self.config.max_tokens,
            "stream": True,
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

        started_at = time.monotonic()
        for attempt in range(self.config.max_retries + 1):
            req = urllib.request.Request(self.config.endpoint, data=body, headers=headers, method="POST")
            try:
                socket_timeout_s = min(
                    self.config.timeout_s,
                    self.config.stream_idle_timeout_s,
                    _remaining_stream_budget(started_at, self.config),
                )
                with urllib.request.urlopen(req, timeout=socket_timeout_s) as resp:
                    return _read_stream_response(resp, self.config, started_at)
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
                    _sleep_within_stream_budget(sleep_s, started_at, self.config)
                    continue
                if 500 <= exc.code < 600 and attempt < self.config.max_retries:
                    _sleep_within_stream_budget(min(2**attempt, 30), started_at, self.config)
                    continue
                raise InferenceError(f"macprovider http {exc.code}", kind=f"http_{exc.code}") from exc
            except (TimeoutError, urllib.error.URLError) as exc:
                _raise_if_stream_deadline_exceeded(started_at, self.config)
                if attempt < self.config.max_retries:
                    _sleep_within_stream_budget(min(2**attempt, 30), started_at, self.config)
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
        classified = _classify_error_code(code)
        if classified in {"quota_exhausted", "burst"}:
            kind = classified
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return kind, retry_after_s, reset_unix


def _classify_error_code(code: str) -> str:
    lowered = code.lower()
    if "quota" in lowered:
        return "quota_exhausted"
    if "rate" in lowered or "burst" in lowered:
        return "burst"
    return "server_error"


def _raise_in_band_error(err: dict) -> None:
    code = str(err.get("code") or "")
    message = f"upstream server_error: {_sanitize_in_band_error_message(err.get('message'))}"
    kind = _classify_error_code(code)
    if kind == "quota_exhausted":
        raise QuotaExhaustedError(message)
    if kind == "burst":
        raise BurstThrottledError(message)
    raise InferenceError(message, kind="server_error")


_IN_BAND_ERROR_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")


def _sanitize_in_band_error_message(message: object) -> str:
    sanitized = _IN_BAND_ERROR_CONTROL_CHARS.sub("", str(message or "upstream streaming error"))
    return sanitized[:200]


def _raise_if_stream_deadline_exceeded(started_at: float, config: InferenceConfig) -> None:
    if time.monotonic() - started_at >= config.stream_total_timeout_s:
        raise InferenceError("SSE total deadline exceeded", kind="stream_truncated")


def _remaining_stream_budget(started_at: float, config: InferenceConfig) -> float:
    remaining = config.stream_total_timeout_s - (time.monotonic() - started_at)
    if remaining <= 0:
        raise InferenceError("SSE total deadline exceeded", kind="stream_truncated")
    return remaining


def _sleep_within_stream_budget(sleep_s: float, started_at: float, config: InferenceConfig) -> None:
    if time.monotonic() + sleep_s >= started_at + config.stream_total_timeout_s:
        raise InferenceError("SSE total deadline exceeded", kind="stream_truncated")
    time.sleep(sleep_s)


def _raw_line_len(raw_line: bytes | str) -> int:
    if isinstance(raw_line, bytes):
        return len(raw_line)
    return len(raw_line.encode("utf-8"))


def _raw_line_endswith_newline(raw_line: bytes | str) -> bool:
    if isinstance(raw_line, bytes):
        return raw_line.endswith(b"\n")
    return raw_line.endswith("\n")


def _read_stream_response(resp, config: InferenceConfig, started_at: float) -> list[str]:
    parser = _SSECompletionParser()
    total_bytes = 0
    last_progress_at = started_at
    while True:
        try:
            now = time.monotonic()
            if now - started_at > config.stream_total_timeout_s:
                raise InferenceError("SSE total deadline exceeded", kind="stream_truncated")
            try:
                raw_line = resp.readline(config.stream_max_line_bytes)
            except TimeoutError as exc:
                now = time.monotonic()
                if now > started_at + config.stream_total_timeout_s:
                    raise InferenceError("SSE total deadline exceeded", kind="stream_truncated") from exc
                raise InferenceError("SSE idle deadline exceeded", kind="stream_idle_timeout") from exc
            now = time.monotonic()
            if now - last_progress_at > config.stream_idle_timeout_s:
                raise InferenceError("SSE idle deadline exceeded", kind="stream_idle_timeout")
            if now - started_at > config.stream_total_timeout_s:
                raise InferenceError("SSE total deadline exceeded", kind="stream_truncated")
            if raw_line == b"" or raw_line == "":
                break
            last_progress_at = now
            line_len = _raw_line_len(raw_line)
            total_bytes += line_len
            if total_bytes > config.stream_max_bytes:
                raise InferenceError("SSE byte cap exceeded", kind="stream_truncated")
            if line_len > config.stream_max_line_bytes or (
                line_len == config.stream_max_line_bytes and not _raw_line_endswith_newline(raw_line)
            ):
                raise InferenceError("SSE line cap exceeded", kind="stream_truncated")
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
            if parser.feed_line(line):
                return parser.finish()
        except InferenceError:
            raise
        except (OSError, ConnectionResetError, http.client.IncompleteRead) as exc:
            raise InferenceError("truncated chat completion stream", kind="stream_truncated") from exc
        except UnicodeDecodeError as exc:
            raise InferenceError("malformed chat completion stream", kind="malformed_response") from exc
    return parser.finish()


def parse_chat_response(raw: bytes) -> list[str]:
    """Legacy non-streaming parser. Retained for backwards-compatibility tests; runtime uses parse_stream_response."""
    try:
        data = json.loads(raw)
        choices = data["choices"]
        return [choice["message"]["content"] for choice in choices]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise InferenceError("malformed chat completion response", kind="malformed_response") from exc


def parse_stream_response(raw_text: str) -> list[str]:
    parser = _SSECompletionParser()
    for raw_line in raw_text.splitlines():
        if parser.feed_line(raw_line):
            break
    return parser.finish()


class _SSECompletionParser:
    def __init__(self) -> None:
        self.content_parts: list[str] = []
        self.data_lines: list[str] = []
        self.saw_done = False

    def feed_line(self, raw_line: str) -> bool:
        line = raw_line.rstrip("\r\n")
        if line == "":
            self._dispatch_buffer()
            return self.saw_done
        if line.startswith(":"):
            return False
        field, value = self._split_field(line)
        if field != "data":
            return False
        if value == "[DONE]":
            self._dispatch_buffer()
            self.saw_done = True
            return True
        self.data_lines.append(value)
        return False

    def finish(self) -> list[str]:
        if not self.saw_done:
            raise InferenceError("truncated chat completion stream", kind="stream_truncated")
        return ["".join(self.content_parts)]

    @staticmethod
    def _split_field(line: str) -> tuple[str, str]:
        if ":" not in line:
            return line, ""
        field, value = line.split(":", 1)
        if value.startswith(" "):
            value = value[1:]
        return field, value

    def _dispatch_buffer(self) -> None:
        if not self.data_lines:
            return
        payload = "\n".join(self.data_lines)
        self.data_lines = []
        self._dispatch_payload(payload)

    def _dispatch_payload(self, payload: str) -> None:
        if payload == "":
            return
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise InferenceError("truncated chat completion stream", kind="stream_truncated") from exc
        try:
            if isinstance(chunk, dict):
                err = chunk.get("error")
                if isinstance(err, dict):
                    _raise_in_band_error(err)
            # OpenAI SSE emits usage-only and other non-content chunks where
            # `choices` is absent or empty (e.g. the final
            # `{"choices":[],"usage":{...}}` token-accounting frame). Those
            # are legitimate protocol frames, not malformed responses.
            choices = chunk.get("choices") if isinstance(chunk, dict) else None
            if not choices:
                return
            choice = choices[0]
            delta = choice.get("delta", {}) if isinstance(choice, dict) else {}
            piece = delta.get("content") if isinstance(delta, dict) else None
            if piece is None:
                return
            if not isinstance(piece, str):
                raise InferenceError("malformed chat completion stream", kind="malformed_response")
            self.content_parts.append(piece)
        except (KeyError, IndexError, TypeError) as exc:
            raise InferenceError("malformed chat completion stream", kind="malformed_response") from exc
