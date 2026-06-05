# arm64golf v0.1 Report

Status: private test bootstrap; not yet run against live `air5` inference.

## Verdict

No PASS/FAIL verdict yet. The search has not started because the air5 operator
handoff and live MacProvider credentials are still pending.

## Current Evidence

- Private GitHub repo exists at `https://github.com/Augustas11/arm64golf` and
  `main` has been pushed there. GitHub reports visibility `PRIVATE`.
- Baseline candidate verifies locally on 1200 deterministic `sort3-arm64`
  tests through the native ARM64 sandbox runner.
- The native runner enforces the v0.1 candidate caps inside the generated
  verifier executable: 100 ms wall-clock by default and 256 MB address/data
  memory by default.
- Baseline score is 18 instructions.
- Seed receipt exists at `receipts/726c3e4c49b5.json`.
- Receipt verification passes with `bin/verify-receipt.py`.
- Static leaderboard contains the seed baseline row.
- Leaderboard exports now include `attempt_count`,
  `requested_candidate_count`, and `candidate_response_count` so PASS/FAIL
  thresholds can be audited from run data.
- The SQLite store records each evaluated response separately from deduped
  candidates, and `bin/summarize-run.py` derives the current verdict from that
  evidence. Failed evaluations preserve sandbox/compiler error text for
  failure-mode analysis.
- The harness enforces `--max-candidate-responses` for live runs and continues
  past PASS-A by default so the same run can still probe for PASS-B/PASS-C.
- `sandbox/profile.sb` starts from deny-by-default and the native sandbox test
  suite blocks filesystem read, filesystem write, network connect, fork, and
  external exec probes. It also verifies that a non-returning candidate is
  terminated by the native timeout path.
- The harness has an offline `--mock-response-file` smoke path that records a
  synthetic attempt through native sandbox verification, scoring, receipt
  signing, SQLite persistence, and leaderboard export without MacProvider
  credentials.
- `bin/preflight.py` and `bin/check-air5-model.py` exist so operator readiness,
  GitHub auth, API-key presence, and coordinator model visibility can be
  checked reproducibly.
- As of 2026-06-05, `https://coordinator.streamvc.live/v1/models` returns 404
  from this environment, while `https://api.streamvc.live/v1/models` returns
  401 without a bearer token. The authenticated API endpoint is the current
  fallback path for model visibility checks.

## Pending Before PASS/FAIL Run

- Complete the air5 coder-model handoff.
- Confirm live provider id and model availability with `bin/check-air5-model.py`.
- Provide `MACPROVIDER_API_KEY` for authenticated model checks and live
  inference.
- Run the search harness with `MACPROVIDER_API_KEY`.
- Deploy `web/` to a preview/private target. Configure `arm64golf.streamvc.live`
  only after explicit public launch approval.

## PASS/FAIL Criteria

- PASS-A: one verified ARM64 candidate within 200 inference calls.
- PASS-B: one verified 17-instruction ARM64 candidate within 10,000 inference
  calls.
- PASS-C: verified 16-instruction candidate or structural diversity beyond
  PASS-B.
- FAIL: none of the above within 10,000 inference calls.
