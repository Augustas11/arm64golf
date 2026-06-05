from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, UTC
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.attest import sign_receipt
from harness.inference import DEFAULT_MODEL, DEFAULT_PROVIDER, InferenceConfig, InferenceError, MacProviderClient
from harness.module import load_problem_module
from harness.prompts import build_prompt, extract_assembly
from harness.store import Store
from sandbox.runner import run_candidate as run_sandboxed_candidate


HARNESS_VERSION = "0.1.0"


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sandbox_verify(problem_dir: Path, module, candidate, timeout_ms: int) -> bool:
    result = run_sandboxed_candidate(problem_dir, candidate.normalized_source, timeout_ms=timeout_ms)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error", "sandbox runner failed")))
    return bool(result.get("verified"))


def receipt_payload(candidate, score: int, model_id: str, provider_id: str) -> dict[str, object]:
    return {
        "problem_id": candidate.problem_id,
        "candidate_hash": candidate.candidate_hash,
        "score": score,
        "model_id": model_id,
        "provider_id": provider_id,
        "harness_version": HARNESS_VERSION,
        "ts": utc_now(),
    }


def sign_and_record_receipt(store: Store, args: argparse.Namespace, candidate, score: int, model_id: str, provider_id: str) -> None:
    payload = receipt_payload(candidate, score, model_id, provider_id)
    receipt = sign_receipt(payload, Path(args.private_key), Path(args.public_key), Path(args.receipts_dir))
    store.record_receipt(candidate.candidate_hash, receipt.path, receipt.signature)


def seed_baseline(store: Store, args: argparse.Namespace, problem_dir: Path, module, model_id: str, provider_id: str, timeout_ms: int) -> None:
    count, source = module.baseline()
    candidate = module.load(source)
    verified = sandbox_verify(problem_dir, module, candidate, timeout_ms)
    store.record_candidate(
        candidate_hash=candidate.candidate_hash,
        problem_id=candidate.problem_id,
        source=candidate.normalized_source,
        score=count,
        verified=verified,
        model_id=model_id,
        provider_id=provider_id,
    )
    if verified:
        sign_and_record_receipt(store, args, candidate, count, model_id, provider_id)


def run(args: argparse.Namespace) -> int:
    problem_dir = Path(args.problem)
    module = load_problem_module(problem_dir)
    store = Store(Path(args.db))
    model_id = args.model
    provider_id = args.provider

    seed_baseline(store, args, problem_dir, module, model_id, provider_id, args.timeout_ms)

    if args.seed_only:
        store.export_leaderboard(module.PROBLEM_ID, Path(args.leaderboard_json))
        return 0

    api_key = args.api_key or os.environ.get("MACPROVIDER_API_KEY")
    if not api_key:
        raise SystemExit("MACPROVIDER_API_KEY is required unless --seed-only is used")

    client = MacProviderClient(
        api_key,
        InferenceConfig(model=model_id, provider=provider_id, n=args.n, temperature=args.temperature, top_p=args.top_p),
    )

    for _ in range(args.rounds):
        best = store.best_candidate(module.PROBLEM_ID)
        current_source = best["source"] if best else module.baseline()[1]
        current_count = int(best["score"]) if best else module.baseline()[0]
        messages = build_prompt(current_source, current_count, args.template)
        try:
            responses = client.complete(messages)
        except InferenceError as exc:
            store.record_attempt(module.PROBLEM_ID, args.template, "inference_error", str(exc))
            continue

        store.record_attempt(module.PROBLEM_ID, args.template, "ok")
        for response in responses:
            candidate = module.load(extract_assembly(response))
            verified = sandbox_verify(problem_dir, module, candidate, args.timeout_ms)
            store.record_candidate(
                candidate_hash=candidate.candidate_hash,
                problem_id=candidate.problem_id,
                source=candidate.normalized_source,
                score=module.score(candidate),
                verified=verified,
                model_id=model_id,
                provider_id=provider_id,
            )
            if verified:
                sign_and_record_receipt(store, args, candidate, module.score(candidate), model_id, provider_id)
        store.export_leaderboard(module.PROBLEM_ID, Path(args.leaderboard_json))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--problem", default=str(REPO_ROOT / "problems" / "sort3-arm64"))
    parser.add_argument("--db", default=str(REPO_ROOT / "data" / "arm64golf.sqlite"))
    parser.add_argument("--leaderboard-json", default=str(REPO_ROOT / "web" / "public" / "leaderboard.json"))
    parser.add_argument("--receipts-dir", default=str(REPO_ROOT / "receipts"))
    parser.add_argument("--private-key", default=str(REPO_ROOT / "data" / "sign.key"))
    parser.add_argument("--public-key", default=str(REPO_ROOT / "receipts" / "PUBKEY"))
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--n", type=int, default=8)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--template", default="no_failed_context")
    parser.add_argument("--timeout-ms", type=int, default=100)
    parser.add_argument("--seed-only", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
