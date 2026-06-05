# arm64golf v0.1 Report

Status: not yet run against live `air5` inference.

## Verdict

No PASS/FAIL verdict yet. The search has not started because the air5 operator
handoff and live MacProvider credentials are still pending.

## Current Evidence

- Baseline candidate verifies locally on 1200 deterministic `sort3-arm64`
  tests.
- Baseline score is 18 instructions.
- Seed receipt exists at `receipts/726c3e4c49b5.json`.
- Receipt verification passes with `bin/verify-receipt.py`.
- Static leaderboard contains the seed baseline row.

## Pending Before PASS/FAIL Run

- Re-authenticate GitHub CLI for `Augustas11`, create the public repo, and push
  `main`.
- Complete the air5 coder-model handoff.
- Confirm live provider id and model availability.
- Run the search harness with `MACPROVIDER_API_KEY`.
- Replace the interpreter-backed sandbox prototype with native assembled
  routine execution before claiming the full hard-sandbox requirement.
- Deploy `web/` and configure `arm64golf.streamvc.live`.

## PASS/FAIL Criteria

- PASS-A: one verified ARM64 candidate within 200 inference calls.
- PASS-B: one verified 17-instruction ARM64 candidate within 10,000 inference
  calls.
- PASS-C: verified 16-instruction candidate or structural diversity beyond
  PASS-B.
- FAIL: none of the above within 10,000 inference calls.
