# arm64golf v0.1 Report

Status: pending

## Verdict

No PASS/FAIL verdict yet. The search has not started because the air5 operator handoff and live MacProvider credentials are still pending.

## Run Evidence

- problem: `sort3-arm64`
- attempts: 0
- requested candidates: 0
- candidate responses: 0
- evaluated responses: 0
- verified evaluations: 0
- failed evaluations: 0
- evaluations with error text: 0
- best verified score: 18
- first verified response: none
- first 17-instruction response: none
- first 16-instruction response: none
- near-best verified candidates: 1
- near-best unique opcode structures: 1

## Structural Diversity Evidence

- `08c76e7641c069f2`: 1 candidate(s), representative `726c3e4c49b5`, score 18, 18 instructions: `cmp csetm eor and eor eor cmp csetm eor and eor eor cmp csetm eor and eor eor`

This evidence is for manual PASS-C review only; automatic PASS-C still requires a verified 16-instruction candidate.

## Completion Gate Audit

- Local repo, license, spec, README, problem module, sandbox, receipts, static leaderboard, and report artifacts are present.
- Local verification currently proves the seed baseline, receipt validation, web artifact validation, sandbox behavior, private GitHub visibility, and full pytest suite.
- PASS/FAIL outcome is not yet available because the live air5 coder-model handoff, `MACPROVIDER_API_KEY`, and real search run are pending.
- `bin/ready-live-run.py` exists as the aggregate gate and remains not-ready until the live operator environment passes preflight and air5 model checks.
- Public deployment and DNS remain intentionally deferred until explicit launch approval.

## Current Evidence

- Private GitHub repo exists at `https://github.com/Augustas11/arm64golf`; public launch is intentionally deferred.
- Baseline candidate verifies locally on 1200 deterministic `sort3-arm64` tests through the native ARM64 sandbox runner.
- The native runner enforces the v0.1 candidate caps inside the generated verifier executable: 100 ms wall-clock by default and 256 MB address/data memory by default.
- Seed receipt exists at `receipts/726c3e4c49b5.json` and is verifiable with `bin/verify-receipt.py`.
- Static leaderboard contains the seed baseline row and run-summary counters.
- `bin/validate-harness-smoke.py` proves the offline harness path with mock inference, sandbox verification, scoring, receipt signing, SQLite persistence, and leaderboard export.
- `bin/validate-sandbox.py` proves the deny-profile contract, native runner, escape-vector pytest suite, timeout, and memory-cap reporting.
- `bin/validate-receipts.py` verifies leaderboard rows against signed receipt payloads.
- `bin/validate-web.py` verifies the static leaderboard HTML/JSON contract.
- `bin/audit-deliverables.py` records local BUILD_PROMPT deliverable status.
- SQLite records every evaluated response separately from deduped candidates, preserving score, verification result, and sandbox/compiler error text.
- `bin/summarize-run.py` and `bin/write-report.py` derive run status from the SQLite attempt/evaluation ledger.
- `bin/ready-live-run.py` aggregates local validation, private repo preflight, credential, and air5 model blockers before live search.
- The harness enforces `--max-candidate-responses` for live runs and continues past PASS-A by default so the same run can still probe for PASS-B/PASS-C.
- `bin/preflight.py` and `bin/check-air5-model.py` exist for reproducible operator readiness and model visibility checks.
- `bin/preflight.py` also verifies the GitHub repo remains private during the test phase unless `--allow-public-launch` is explicitly used after launch approval.

## Pending Before PASS/FAIL Run

- Complete the air5 coder-model handoff.
- Confirm live provider id and model availability with `bin/check-air5-model.py`.
- Provide `MACPROVIDER_API_KEY` for authenticated model checks and live inference.
- Run `bin/ready-live-run.py --run-tests --json` in the operator environment and resolve all blockers.
- Run the search harness with `MACPROVIDER_API_KEY`.
- Deploy `web/` to a preview/private target if needed. Configure `arm64golf.streamvc.live` only after explicit public launch approval.

## PASS/FAIL Criteria

- PASS-A: one verified ARM64 candidate within 200 evaluated candidate responses.
- PASS-B: one verified 17-instruction ARM64 candidate within 10,000 evaluated candidate responses.
- PASS-C: verified 16-instruction candidate or manually reviewed structural diversity beyond PASS-B.
- FAIL: none of the above within 10,000 evaluated candidate responses.
