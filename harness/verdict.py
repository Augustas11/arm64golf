from __future__ import annotations

from typing import Any


SEARCH_OPEN_VERDICTS = {"PENDING", "RUNNING", "PASS-A"}


def verdict(summary: dict[str, Any]) -> str:
    responses = int(summary["candidate_response_count"] or 0)
    first_verified = summary["first_verified_response"]
    first_17 = summary["first_17_response"]
    first_16 = summary["first_16_response"]

    if first_16 is not None and int(first_16) <= 10_000:
        return "PASS-C"
    if first_17 is not None and int(first_17) <= 10_000:
        return "PASS-B"
    if first_verified is not None and int(first_verified) <= 200:
        return "PASS-A"
    if responses >= 10_000:
        return "FAIL"
    if responses == 0:
        return "PENDING"
    return "RUNNING"


def is_search_terminal(summary: dict[str, Any]) -> bool:
    return verdict(summary) not in SEARCH_OPEN_VERDICTS
