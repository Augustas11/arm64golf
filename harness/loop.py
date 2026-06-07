from __future__ import annotations

import argparse
import json
import os
import sys
from hashlib import sha256
from datetime import datetime, UTC
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.attest import sign_receipt
from harness.inference import DEFAULT_MODEL, DEFAULT_PROVIDER, InferenceConfig, InferenceError, MacProviderClient
from harness.module import load_problem_module
from harness.prompts import ABLATION_TEMPLATES, build_prompt, extract_assembly, template_id
from harness.store import SEED_MODEL_ID, SEED_PROVIDER_ID, Store
from harness.verdict import is_search_terminal
from sandbox.runner import run_candidate as run_sandboxed_candidate


HARNESS_VERSION = "0.2.0"
ATTESTATION_FIELDS = ("kind", "details")
REFERENCE_ATTESTATION_DETAIL_FIELDS = ("template_id", "template_name", "temperature", "top_p", "n")
EMPTY_DETAILS_ATTESTATION_KINDS = frozenset({"seed-baseline", "legacy-v1-unknown", "mock"})


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sandbox_result(problem_dir: Path, module, candidate, timeout_ms: int, memory_limit_mb: int) -> dict[str, object]:
    result = run_sandboxed_candidate(
        problem_dir,
        candidate.normalized_source,
        timeout_ms=timeout_ms,
        memory_limit_mb=memory_limit_mb,
    )
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error", "sandbox runner failed")))
    return result


def sandbox_verify(problem_dir: Path, module, candidate, timeout_ms: int, memory_limit_mb: int) -> bool:
    return bool(sandbox_result(problem_dir, module, candidate, timeout_ms, memory_limit_mb).get("verified"))


def require_pinned_attribution(model_id: str, provider_id: str, *, mock: bool, seed_only: bool) -> None:
    if mock or seed_only:
        return
    if model_id != DEFAULT_MODEL:
        raise SystemExit(f"live runs must use pinned model {DEFAULT_MODEL}; got {model_id}")
    if provider_id != DEFAULT_PROVIDER:
        raise SystemExit(f"live runs must use pinned provider {DEFAULT_PROVIDER}; got {provider_id}")


def fallback_candidate_hash(response: str) -> str:
    return sha256(response.encode("utf-8")).hexdigest()


def seed_attestation() -> dict[str, object]:
    return {"kind": "seed-baseline", "details": {}}


def legacy_v1_unknown_attestation() -> dict[str, object]:
    return {"kind": "legacy-v1-unknown", "details": {}}


def mock_attestation() -> dict[str, object]:
    return {"kind": "mock", "details": {}}


def reference_attestation(template_name: str, temperature: float, top_p: float, n: int) -> dict[str, object]:
    validate_reference_attestation_inputs(template_name, temperature, top_p, n)
    return {
        "kind": "reference-harness",
        "details": {
            "template_id": template_id(template_name),
            "template_name": template_name,
            "temperature": temperature,
            "top_p": top_p,
            "n": n,
        },
    }


def validate_reference_attestation_inputs(template_name: str, temperature: float, top_p: float, n: int) -> None:
    if template_name not in ABLATION_TEMPLATES:
        raise ValueError(f"unknown template_name: {template_name!r}")
    if not isinstance(temperature, float) or isinstance(temperature, bool) or not 0.0 <= temperature <= 2.0:
        raise ValueError("temperature must be a float in [0.0, 2.0]")
    if not isinstance(top_p, float) or isinstance(top_p, bool) or not 0.0 < top_p <= 1.0:
        raise ValueError("top_p must be a float in (0.0, 1.0]")
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 64:
        raise ValueError("n must be an int in [1, 64]")


def validate_attestation(attestation: dict[str, object]) -> None:
    if set(attestation.keys()) != set(ATTESTATION_FIELDS):
        raise ValueError(f"attestation fields must be {ATTESTATION_FIELDS}")
    kind = attestation["kind"]
    details = attestation["details"]
    if not isinstance(kind, str) or not kind:
        raise ValueError("attestation kind must be a non-empty string")
    if not isinstance(details, dict):
        raise ValueError("attestation details must be an object")
    if kind in EMPTY_DETAILS_ATTESTATION_KINDS:
        if details:
            raise ValueError(f"{kind} attestation details must be empty")
        return
    if kind == "reference-harness":
        validate_reference_attestation_details(details)
        return
    try:
        json.dumps(details, sort_keys=True)
    except TypeError as exc:
        raise ValueError("unknown attestation details must be JSON-serializable") from exc


def validate_reference_attestation_details(details: dict[str, object]) -> None:
    if set(details.keys()) != set(REFERENCE_ATTESTATION_DETAIL_FIELDS):
        raise ValueError(f"reference-harness details fields must be {REFERENCE_ATTESTATION_DETAIL_FIELDS}")
    template_name = details["template_name"]
    template_id_value = details["template_id"]
    temperature = details["temperature"]
    top_p = details["top_p"]
    n = details["n"]
    if not isinstance(template_name, str):
        raise ValueError("reference-harness template_name must be a string")
    validate_reference_attestation_inputs(template_name, temperature, top_p, n)  # type: ignore[arg-type]
    if not isinstance(template_id_value, str):
        raise ValueError("reference-harness template_id must be a string")
    expected_template_id = template_id(template_name)
    if template_id_value != expected_template_id:
        raise ValueError(f"reference-harness template_id must be {expected_template_id}")


def receipt_payload(
    candidate,
    score: int,
    model_id: str,
    provider_id: str,
    attestation: dict[str, object],
) -> dict[str, object]:
    validate_attestation(attestation)
    return {
        "attestation": attestation,
        "problem_id": candidate.problem_id,
        "candidate_hash": candidate.candidate_hash,
        "score": score,
        "model_id": model_id,
        "provider_id": provider_id,
        "harness_version": HARNESS_VERSION,
        "ts": utc_now(),
    }


def sign_and_record_receipt(
    store: Store,
    args: argparse.Namespace,
    candidate,
    score: int,
    model_id: str,
    provider_id: str,
    attestation: dict[str, object],
) -> None:
    payload = receipt_payload(candidate, score, model_id, provider_id, attestation)
    receipt = sign_receipt(payload, Path(args.private_key), Path(args.public_key), Path(args.receipts_dir))
    store.record_receipt(candidate.candidate_hash, receipt.path, receipt.signature)


def load_mock_responses(path: str) -> list[str]:
    if not path:
        return []
    text = Path(path).read_text()
    stripped = text.strip()
    if stripped.startswith("["):
        import json

        values = json.loads(stripped)
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError("--mock-response-file JSON must be a list of strings")
        return values
    return [text]


def seed_baseline(
    store: Store,
    args: argparse.Namespace,
    problem_dir: Path,
    module,
    timeout_ms: int,
    memory_limit_mb: int,
) -> None:
    count, source = module.baseline()
    candidate = module.load(source)
    verified = sandbox_verify(problem_dir, module, candidate, timeout_ms, memory_limit_mb)
    store.record_candidate(
        candidate_hash=candidate.candidate_hash,
        problem_id=candidate.problem_id,
        source=candidate.normalized_source,
        score=count,
        verified=verified,
        model_id=SEED_MODEL_ID,
        provider_id=SEED_PROVIDER_ID,
    )
    if verified:
        sign_and_record_receipt(store, args, candidate, count, SEED_MODEL_ID, SEED_PROVIDER_ID, seed_attestation())


def run(args: argparse.Namespace) -> int:
    problem_dir = Path(args.problem)
    module = load_problem_module(problem_dir)
    store = Store(Path(args.db))
    model_id = args.model
    provider_id = args.provider
    mock_responses = load_mock_responses(args.mock_response_file)
    require_pinned_attribution(model_id, provider_id, mock=bool(mock_responses), seed_only=args.seed_only)

    seed_baseline(store, args, problem_dir, module, args.timeout_ms, args.memory_limit_mb)

    if args.seed_only:
        store.export_leaderboard(module.PROBLEM_ID, Path(args.leaderboard_json))
        return 0

    api_key = args.api_key or os.environ.get("MACPROVIDER_API_KEY", "")
    demo_token = getattr(args, "demo_token", "") or os.environ.get("MACPROVIDER_DEMO_TOKEN", "")
    if not api_key and not demo_token and not mock_responses:
        raise SystemExit(
            "set MACPROVIDER_API_KEY or MACPROVIDER_DEMO_TOKEN (or pass --seed-only / --mock-response-file)"
        )

    for _ in range(args.rounds):
        before_summary = store.run_summary(module.PROBLEM_ID)
        remaining = remaining_responses(before_summary, args.max_candidate_responses)
        if remaining == 0:
            store.export_leaderboard(module.PROBLEM_ID, Path(args.leaderboard_json))
            break
        request_n = min(args.n, remaining) if remaining is not None else args.n

        best = store.best_candidate(module.PROBLEM_ID)
        current_source = best["source"] if best else module.baseline()[1]
        current_count = int(best["score"]) if best else module.baseline()[0]
        messages = build_prompt(current_source, current_count, args.template)
        if mock_responses:
            responses = mock_responses[:request_n]
            attempt_id = store.record_attempt(
                module.PROBLEM_ID,
                args.template,
                "mock_ok",
                requested_n=len(responses),
                response_count=len(responses),
            )
        else:
            client = MacProviderClient(
                api_key,
                InferenceConfig(
                    model=model_id,
                    provider=provider_id,
                    n=request_n,
                    temperature=args.temperature,
                    top_p=args.top_p,
                    inter_call_sleep_s=args.inter_call_sleep_s,
                    max_tokens=args.max_tokens,
                ),
                demo_token=demo_token,
            )
            try:
                responses = client.complete(messages)
            except InferenceError as exc:
                # `kind` is a short stable label (quota_exhausted,
                # burst_throttled, auth_failed, provider_unreachable, ...);
                # `error` carries the human message. Logging both makes
                # post-mortem queries trivially filterable.
                status_kind = getattr(exc, "kind", "inference_error")
                store.record_attempt(
                    module.PROBLEM_ID,
                    args.template,
                    status_kind,
                    str(exc),
                    requested_n=request_n,
                    response_count=0,
                )
                # Stop the run on terminal failures — daily quota gone or
                # credential rejected. Continuing would just log the same
                # failure repeatedly until --rounds runs out.
                if status_kind in {"quota_exhausted", "auth_failed", "no_credential"}:
                    print(f"halting run: {status_kind} — {exc}")
                    break
                continue

            attempt_id = store.record_attempt(
                module.PROBLEM_ID,
                args.template,
                "ok",
                requested_n=request_n,
                response_count=len(responses),
            )
        for response in responses:
            candidate = None
            score = 0
            candidate_hash = fallback_candidate_hash(response)
            problem_id = module.PROBLEM_ID
            verified = False
            error = ""
            receipt_model_id = model_id
            receipt_provider_id = provider_id
            try:
                candidate = module.load(extract_assembly(response))
                problem_id = candidate.problem_id
                candidate_hash = candidate.candidate_hash
                score = module.score(candidate)
                result = sandbox_result(problem_dir, module, candidate, args.timeout_ms, args.memory_limit_mb)
                verified = bool(result.get("verified"))
                error = str(result.get("error") or "")
                store.record_candidate(
                    candidate_hash=candidate.candidate_hash,
                    problem_id=candidate.problem_id,
                    source=candidate.normalized_source,
                    score=score,
                    verified=verified,
                    model_id=model_id,
                    provider_id=provider_id,
                )
                row = store.candidate(candidate.problem_id, candidate.candidate_hash)
                if row is not None:
                    receipt_model_id = str(row["model_id"])
                    receipt_provider_id = str(row["provider_id"])
            except Exception as exc:  # noqa: BLE001 - candidate-specific failures must be ledgered.
                error = f"{type(exc).__name__}: {exc}"
            store.record_evaluation(
                attempt_id=attempt_id,
                problem_id=problem_id,
                candidate_hash=candidate_hash,
                score=score,
                verified=verified,
                error=error,
            )
            if verified and candidate is not None:
                sign_and_record_receipt(
                    store,
                    args,
                    candidate,
                    score,
                    receipt_model_id,
                    receipt_provider_id,
                    mock_attestation()
                    if mock_responses
                    else reference_attestation(args.template, args.temperature, args.top_p, args.n),
                )
        store.export_leaderboard(module.PROBLEM_ID, Path(args.leaderboard_json))
        if args.stop_on_verdict and is_search_terminal(store.run_summary(module.PROBLEM_ID)):
            break
    return 0


def remaining_responses(summary: dict[str, object], max_candidate_responses: int) -> int | None:
    if max_candidate_responses <= 0:
        return None
    used = int(summary["candidate_response_count"] or 0)
    return max(max_candidate_responses - used, 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--problem", default=str(REPO_ROOT / "problems" / "sort3-arm64"))
    parser.add_argument("--db", default=str(REPO_ROOT / "data" / "arm64golf.sqlite"))
    parser.add_argument("--leaderboard-json", default=str(REPO_ROOT / "web" / "public" / "leaderboard.json"))
    parser.add_argument("--receipts-dir", default=str(REPO_ROOT / "receipts"))
    parser.add_argument("--private-key", default=str(REPO_ROOT / "data" / "sign.key"))
    parser.add_argument("--public-key", default=str(REPO_ROOT / "receipts" / "PUBKEY"))
    parser.add_argument("--api-key", default="")
    parser.add_argument("--demo-token", default="")
    parser.add_argument(
        "--inter-call-sleep-s",
        type=float,
        default=0.5,
        help="seconds to sleep between successive single-completion calls in a fanned-out batch (prevents per-minute burst throttling).",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--n", type=int, default=8)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=256,
        help="per-call max_tokens cap. Bounds wall-clock per call so the gateway/coordinator timeout becomes a fallback, not a load-bearing knob.",
    )
    parser.add_argument("--template", default="no_failed_context")
    parser.add_argument("--timeout-ms", type=int, default=100)
    parser.add_argument("--memory-limit-mb", type=int, default=256)
    parser.add_argument("--max-candidate-responses", type=int, default=10_000)
    parser.add_argument("--no-stop-on-verdict", dest="stop_on_verdict", action="store_false")
    parser.add_argument("--mock-response-file", default="")
    parser.add_argument("--seed-only", action="store_true")
    parser.set_defaults(stop_on_verdict=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
