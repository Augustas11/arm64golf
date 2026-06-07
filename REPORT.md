# arm64golf v0.1 Report

Status: pass-c

## Verdict

Current derived verdict: PASS-C.

## Run Evidence

- problem: `sort3-arm64`
- attempts: 90
- requested candidates: 720
- candidate responses: 328
- evaluated responses: 328
- verified evaluations: 111
- failed evaluations: 217
- evaluations with error text: 217
- best verified score: 12
- first verified response: 2
- first 17-instruction response: 115
- first 16-instruction response: 115
- near-best verified candidates: 2
- near-best unique opcode structures: 1

## Structural Diversity Evidence

- `f13bac4e5383f523`: 2 candidate(s), representative `57b2aa236342`, score 12, 12 instructions: `cmp csel csel mov cmp csel csel mov cmp csel csel mov`

This evidence is for manual PASS-C review only; automatic PASS-C still requires a verified 16-instruction candidate.

## Top Evaluation Errors

- 100x case 1 failed
- 65x case 2 failed
- 1x sandbox/candidate.s:6:5: error: unexpected token at start of statement
    1. **Block 1**: `cmp x0, x1 / csel x3, x1, x0, le / csel x0, x0, x1, le / mov x1, x3`
    ^
sandbox/candidate.s:7:5: error: unexpected token at start of statement
    - **Comparison**: `x0 <= x1`
    ^
sandbox/candidate.s:8:5: error: unexpected token at start of statement
    - **Reads**: `x0, x1`
    ^
sandbox/candidate.s:9:5: error: unexpected token at start of statement
    - **Mutates**: `x0, x1, x3`
    ^
sandbox/candidate.s:10:5: error: unexpected token at start of statement
    - **Untouched**: `x2`
    ^
sandbox/candidate.s:11:5: error: unexpected token at start of statement
    - **Necessary**: Yes, ensures `x0 <= x1` before further comparisons.
    ^
sandbox/candidate.s:12:5: error: unexpected token at start of statement
    2. **Block 2**: `cmp x1, x2 / csel x3, x2, x1, le / csel x1, x1, x2, le / mov x2, x3`
    ^
sandbox/candidate.s:13:5: error: unexpected token at start of statement
    - **Comparison**: `x1 <= x2`
    ^
sandbox/candidate.s:14:5: error: unexpected token at start of statement
    - **Reads**: `x1, x2`
    ^
sandbox/candidate.s:15:5: error: unexpected token at start of statement
    - **Mutates**: `x1, x2, x3`
    ^
sandbox/candidate.s:16:5: error: unexpected token at start of statement
    - **Untouched**: `x0`
    ^
sandbox/candidate.s:17:5: error: unexpected token at start of statement
    - **Necessary**: Yes, ensures `x1 <= x2` before further comparisons.
    ^
sandbox/candidate.s:18:5: error: unexpected token at start of statement
    3. **Block 3**: `cmp x0, x1 / csel x3, x1, x0, le / csel x0, x0, x1, le / mov x1, x3`
    ^
sandbox/candidate.s:19:5: error: unexpected token at start of statement
    - **Comparison**: `x0 <= x1`
    ^
sandbox/candidate.s:20:5: error: unexpected token at start of statement
    - **Reads**: `x0, x1`
    ^
sandbox/candidate.s:21:5: error: unexpected token at start of statement
    - **Mutates**: `x0, x1, x3`
    ^
sandbox/candidate.s:22:5: error: unexpected token at start of statement
    - **Untouched**: `x2`
    ^
sandbox/candidate.s:23:5: error: unexpected token at start of statement
    - **Necessary**: No, redundant with Block 1.
    ^
sandbox/candidate.s:25:19: error: unexpected token in argument list
    The redundant block is Block 3, which is identical to Block 1 and does not add any new information or necessary operations. This block can be eliminated.
                  ^
sandbox/candidate.s:27:5: error: invalid character in input
    ```arm64
    ^
sandbox/candidate.s:27:5: error: unexpected token at start of statement
    ```arm64
    ^
sandbox/candidate.s:35:5: error: too few operands for instruction
    mov
    ^~~
- 1x sandbox/candidate.s:7:5: error: unrecognized instruction mnemonic
    teqz x3, x3
    ^
sandbox/candidate.s:15:5: error: unrecognized instruction mnemonic
    teqz x3, x3
    ^
sandbox/candidate.s:23:5: error: unrecognized instruction mnemonic
    teqz x3, x3
    ^
sandbox/candidate.s:8:10: error: directional label undefined
    b.eq 1f
         ^
sandbox/candidate.s:16:10: error: directional label undefined
    b.eq 2f
         ^
sandbox/candidate.s:24:10: error: directional label undefined
    b.eq 3f
         ^
- 1x sandbox/candidate.s:20:10: error: invalid operand for instruction
    eors x0, x0, x3
         ^
sandbox/candidate.s:21:10: error: invalid operand for instruction
    eors x1, x1, x4
         ^
sandbox/candidate.s:22:10: error: invalid operand for instruction
    eors x2, x2, x7
         ^

## Completion Gate Audit

- Local repo, license, spec, README, problem module, sandbox, receipts, static leaderboard, and report artifacts are present.
- Local verification currently proves the seed baseline, receipt validation, web artifact validation, sandbox behavior, private GitHub visibility, and full pytest suite.
- PASS/FAIL outcome is not yet available because the live air5 coder-model handoff, `MACPROVIDER_API_KEY`, and real search run are pending.
- `bin/ready-live-run.py` exists as the aggregate gate and remains not-ready until the live operator environment passes preflight and air5 model checks.
- Public deployment and DNS remain intentionally deferred until explicit launch approval.

## Current Evidence

- Private GitHub repo exists at `https://github.com/Augustas11/arm64golf`; public launch is intentionally deferred.
- Baseline candidate verifies locally on 1200 deterministic `sort3-arm64` tests through the native ARM64 sandbox runner.
- The seed baseline row is attributed to `reference-baseline` / `local-harness`; only live model responses may carry `air5` + coder-model attribution.
- The native runner enforces the v0.1 candidate caps inside the generated verifier executable: 100 ms wall-clock by default and 256 MB address/data memory by default.
- Seed receipt exists at `receipts/726c3e4c49b5.json` and is verifiable with `bin/verify-receipt.py`.
- Static leaderboard contains the seed baseline row and run-summary counters.
- `bin/validate-docs.py` proves `SPEC.md` and `README.md` still satisfy the required private-test, recruiting, and no-overclaim contracts.
- `bin/validate-harness-smoke.py` proves the offline harness path with mock inference, sandbox verification, scoring, receipt signing, SQLite persistence, and leaderboard export.
- `bin/validate-live-run-contract.py` proves response caps, failed-evaluation logging, response ordinals, receipt export, and pinned live-run attribution before a live run.
- `bin/validate-inference-config.py` proves the pinned MacProvider endpoint, coder model, air5 provider header, sampling defaults, and authentication failure behavior.
- `bin/validate-sandbox.py` proves the deny-profile contract, native runner, escape-vector pytest suite, timeout, and memory-cap reporting.
- `bin/validate-receipts.py` verifies leaderboard rows against signed receipt payloads.
- `bin/validate-report.py` verifies this report is generated from tracked leaderboard evidence and preserves pending live-run gates.
- `bin/validate-air5-handoff.py` verifies the air5 operator note and no-touch owner coordination rules.
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
