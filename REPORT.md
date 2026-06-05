# arm64golf v0.1 Report

Status: pass-a

## Network configuration this canary depended on

The v0.3 canary ran against production MacProvider at api.streamvc.live,
with the following non-default config in effect:

- `gateway.timeouts.coordinator_header_timeout_seconds: 60` (default: 10;
  bumped 2026-06-05 because a 10s ceiling truncated any non-streaming
  inference exceeding 10s of generation).
- `coordinator.ws.write_timeout_s: 60` (default: 10; same reason).
- `gateway.quotas.account_daily_tokens: 20000000` (default: 100000;
  default was insufficient for a single 200-call canary).

These were operator config changes made during v0.1 / v0.2 sessions to
unblock the canary; they remain in effect on Pearl VPS (159.223.165.194)
as the network's standing config. A future "clean default config"
canary would need to either run with non-default timeouts, switch to
streaming, or restrict the workload to fit the defaults.

The v0.3 harness adds its own bound on the buyer side
(`InferenceConfig.max_tokens=256`, threaded through to the chat
completions payload) so the 60s timeouts behave as a fallback rather
than a load-bearing knob. The bound was implicit during the v0.3
canary (default).

## Verdict Interpretation

The harness's auto-derived verdict (recorded verbatim in the
`## Verdict` section below) is PASS-A whenever any verified candidate
exists. Two readings need to be kept distinct:

- **PASS-A (technical)** — at least one verified candidate, regardless
  of whether its normalized hash matches the baseline `726c3e4c49b5`.
  v0.1, v0.2, and v0.3 all hit this. It says the harness, sandbox,
  inference path, and receipt pipeline work end-to-end.
- **PASS-A (substantive)** — at least one verified candidate with a
  normalized hash that is NOT `726c3e4c49b5`. Even a rediscovery of
  the same logical 18-instruction routine with different register
  allocation would count. v0.3 DOES hit this: the leaderboard ends
  with four rows — the baseline `726c3e4c49b5` (score 18, rank 1) and
  three distinct verified non-baseline candidates `47f0dd8d0a24`,
  `f41b055a1965`, and `17e628abfc2b`, each scoring 24 instructions.
  These are correct sort3 routines (all 1200 deterministic test
  cases pass through the sandboxed runner) that happen to be longer
  than the reference — i.e. the model found genuinely new logic, just
  not denser logic. They are signed and verifiable via
  `bin/verify-receipt.py receipts/<hash>.json`.

v0.3 reading: the network supported the workload (30 attempts, 105
responses, zero `provider_unreachable` / `quota_exhausted` /
`auth_failed` / `burst_throttled` terminal halts; the run completed
without operator intervention), and the search discovered three
distinct non-baseline verified routines at score 24 — but no verified
candidate at the baseline's score 18 or below (`first_17_response:
none`). Dominant failure modes are unchanged from v0.1 / v0.2: `case
2 failed` (already-ascending input), `case 1 failed` (all-equal
triple), and ISA mnemonic errors (`eors`, `eorr`, `teqz`, `or`) even
though the `failed_context` template explicitly surfaces them. v0.3
is therefore best read as **PASS-A (substantive), NOT PASS-B**: the
loop's search yields genuine non-baseline correctness, but is not yet
producing candidates dense enough to break or tie the 18-instruction
reference.

## Verdict

Current derived verdict: PASS-A.

## Run Evidence

- problem: `sort3-arm64`
- attempts: 30
- requested candidates: 240
- candidate responses: 105
- evaluated responses: 105
- verified evaluations: 54
- failed evaluations: 51
- evaluations with error text: 51
- best verified score: 18
- first verified response: 2
- first 17-instruction response: none
- first 16-instruction response: none
- near-best verified candidates: 1
- near-best unique opcode structures: 1

## Structural Diversity Evidence

- `08c76e7641c069f2`: 1 candidate(s), representative `726c3e4c49b5`, score 18, 18 instructions: `cmp csetm eor and eor eor cmp csetm eor and eor eor cmp csetm eor and eor eor`

This evidence is for manual PASS-C review only; automatic PASS-C still requires a verified 16-instruction candidate.

## Top Evaluation Errors

- 17x case 2 failed
- 7x case 1 failed
- 1x /private/tmp/arm64golf-sandbox/run-2478qtx3/candidate.s:7:5: error: unrecognized instruction mnemonic
    teqz x3, x3
    ^
/private/tmp/arm64golf-sandbox/run-2478qtx3/candidate.s:15:5: error: unrecognized instruction mnemonic
    teqz x3, x3
    ^
/private/tmp/arm64golf-sandbox/run-2478qtx3/candidate.s:23:5: error: unrecognized instruction mnemonic
    teqz x3, x3
    ^
/private/tmp/arm64golf-sandbox/run-2478qtx3/candidate.s:8:10: error: directional label undefined
    b.eq 1f
         ^
/private/tmp/arm64golf-sandbox/run-2478qtx3/candidate.s:16:10: error: directional label undefined
    b.eq 2f
         ^
/private/tmp/arm64golf-sandbox/run-2478qtx3/candidate.s:24:10: error: directional label undefined
    b.eq 3f
         ^
- 1x /private/tmp/arm64golf-sandbox/run-3s3ho4w8/candidate.s:20:10: error: invalid operand for instruction
    eors x0, x0, x3
         ^
/private/tmp/arm64golf-sandbox/run-3s3ho4w8/candidate.s:21:10: error: invalid operand for instruction
    eors x1, x1, x4
         ^
/private/tmp/arm64golf-sandbox/run-3s3ho4w8/candidate.s:22:10: error: invalid operand for instruction
    eors x2, x2, x7
         ^
- 1x /private/tmp/arm64golf-sandbox/run-60y0oe_z/candidate.s:7:5: error: unrecognized instruction mnemonic, did you mean: eor, eor3, orr?
    eorr x4, x0, x1
    ^
/private/tmp/arm64golf-sandbox/run-60y0oe_z/candidate.s:9:5: error: unrecognized instruction mnemonic, did you mean: eor, eor3, orr?
    eorr x0, x0, x4
    ^
/private/tmp/arm64golf-sandbox/run-60y0oe_z/candidate.s:10:5: error: unrecognized instruction mnemonic, did you mean: eor, eor3, orr?
    eorr x1, x1, x4
    ^
/private/tmp/arm64golf-sandbox/run-60y0oe_z/candidate.s:13:5: error: unrecognized instruction mnemonic, did you mean: eor, eor3, orr?
    eorr x4, x1, x2
    ^
/private/tmp/arm64golf-sandbox/run-60y0oe_z/candidate.s:15:5: error: unrecognized instruction mnemonic, did you mean: eor, eor3, orr?
    eorr x1, x1, x4
    ^
/private/tmp/arm64golf-sandbox/run-60y0oe_z/candidate.s:16:5: error: unrecognized instruction mnemonic, did you mean: eor, eor3, orr?
    eorr x2, x2, x4
    ^
/private/tmp/arm64golf-sandbox/run-60y0oe_z/candidate.s:19:5: error: unrecognized instruction mnemonic, did you mean: eor, eor3, orr?
    eorr x4, x0, x1
    ^
/private/tmp/arm64golf-sandbox/run-60y0oe_z/candidate.s:21:5: error: unrecognized instruction mnemonic, did you mean: eor, eor3, orr?
    eorr x0, x0, x4
    ^
/private/tmp/arm64golf-sandbox/run-60y0oe_z/candidate.s:22:5: error: unrecognized instruction mnemonic, did you mean: eor, eor3, orr?
    eorr x1, x1, x4
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
