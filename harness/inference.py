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


class InferenceError(RuntimeError):
    pass


class MacProviderClient:
    def __init__(self, api_key: str, config: InferenceConfig | None = None):
        self.api_key = api_key
        self.config = config or InferenceConfig()

    def complete(self, messages: list[dict[str, str]]) -> list[str]:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "n": self.config.n,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "X-MacProvider-Provider": self.config.provider,
        }

        for attempt in range(self.config.max_retries + 1):
            req = urllib.request.Request(self.config.endpoint, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.config.timeout_s) as resp:
                    raw = resp.read()
                return parse_chat_response(raw)
            except urllib.error.HTTPError as exc:
                if exc.code in {401, 403}:
                    raise InferenceError("authentication failed") from exc
                if exc.code == 429:
                    retry_after = exc.headers.get("Retry-After")
                    sleep_s = float(retry_after) if retry_after else min(2**attempt, 30)
                    time.sleep(sleep_s)
                    continue
                if 500 <= exc.code < 600 and attempt < self.config.max_retries:
                    time.sleep(min(2**attempt, 30))
                    continue
                raise InferenceError(f"macprovider http {exc.code}") from exc
            except (TimeoutError, urllib.error.URLError) as exc:
                if attempt < self.config.max_retries:
                    time.sleep(min(2**attempt, 30))
                    continue
                raise InferenceError("provider offline or timed out") from exc
        raise InferenceError("inference retries exhausted")


def parse_chat_response(raw: bytes) -> list[str]:
    try:
        data = json.loads(raw)
        choices = data["choices"]
        return [choice["message"]["content"] for choice in choices]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise InferenceError("malformed chat completion response") from exc
