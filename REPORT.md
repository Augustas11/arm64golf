# arm64golf v0.1 Report

Status: pass-c

## Network configuration this canary depended on

The v0.3 canary and the v0.3 post-canary probes (csel_hint,
dual_example, temperature sweep) all ran against production
MacProvider at api.streamvc.live, with the following non-default
config in effect:

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
than a load-bearing knob.

## Verdict Interpretation

The harness's auto-derived verdict (recorded verbatim in the
`## Verdict` section below) is PASS-C because the best verified
candidate is 12 instructions, below the 16-instruction PASS-C
threshold. Three readings need to be kept distinct:

- **PASS-A (substantive)** — at least one verified candidate with a
  normalized hash that is NOT the baseline `726c3e4c49b5`. The v0.3
  canary cleared this with three verified non-baseline 24-instruction
  routines (`47f0dd8d0a24`, `f41b055a1965`, `17e628abfc2b`).

- **PASS-B (≤17 instructions verified)** — cleared by the v0.3
  post-canary `csel_hint` probe: `57b2aa236342`, 12 instructions,
  three cmp + csel + csel + mov blocks (one per comparator in a
  sort-three network).

- **PASS-C (≤16 instructions verified)** — same candidate clears
  this threshold (12 ≤ 16).

**Honest caveat on the PASS-B/PASS-C win.** The 12-instruction
routine is the literal 4-instruction csel pattern from the
`csel_hint` prompt's worked example, tiled three times — the model
pattern-matched the example rather than discovering the structure
from scratch. The receipt is real (the routine passes all 1200
deterministic test cases through the sandboxed runner) and the
leaderboard claim is honest, but the credit for the compression
goes to the prompt engineer, not to model search.

## Search Discovery — what the post-canary probes found

The dual_example probe (200-cap, withholds the csel pattern but
still names the goal) and the temperature sweep (dual_example ×
temp ∈ {0.3, 0.5, 0.9}, 32-call segments at each setting) together
test whether Qwen2.5-Coder-7B-4bit can search for denser structure
on its own:

| stage | new evals | verified | unique verified hashes | best score |
|---|---|---|---|---|
| dual_example @ temp=0.7 | 93 | 21 | +2 (lt-variant 12, redundant 16) | 12 |
| temp=0.3 segment | 22 | 18 | +0 | 12 |
| temp=0.5 segment | 21 | 13 | +0 | 12 |
| temp=0.9 segment | 22 | 4 | +0 | 12 |

Across the four probes (158 new evaluations, 56 new verified
candidates), **only two unique verified hashes appeared, both at
score 12, both csel-tile variants** (`57b2aa236342` with `le`,
`b4d6f989140e` with `lt`). Zero candidates below 12. Zero new
structures.

Per-temperature pattern:
- Lower temperature converges the model on whatever it considers the
  best routine — at 0.3, 18 of 22 evaluations verified, all at 12,
  only 4 case-1 failures.
- Higher temperature buys broken ARM64, not creative compression. At
  0.9, the verified rate collapses to 4/22, case-1 failures spike to
  14, and the verified pile is still nothing but the same csel
  pattern.

Error mode shift confirms the reading. The dual_example block did
NOT carry the csel pattern, so without that scaffolding the model
regressed to unconditional-swap routines: case-1 (all-equal triple)
failures climbed from 15x in the v0.3 canary to 92x across the
combined probes, and case-2 (already-ascending) from 18x to 43x.
csel_hint was acting as training wheels for both compression *and*
edge-case correctness, not just compression.

**Reading.** For Qwen2.5-Coder-7B-Instruct-4bit on air5 under the
v0.3 prompt family and the sampling temperatures we tested, the
instruction-count floor is **12, reachable only when the prompt
names the csel pattern explicitly**. The model appears to have
exactly two sort3 routines in its working repertoire — the
18-instruction bitmask-eor pattern (the baseline shape) and the
12-instruction csel pattern — and only produces the latter under
explicit prompting. More tokens of the same prompt and more
sampling temperatures do not unlock new structure.

Caveats on the reading:

- Prompt sophistication has not been exhausted. Chain-of-thought,
  self-critique loops, and instruction-deletion framings have not
  been tried. Calibrated prior on whether CoT breaks the 12-floor
  on 7B: ~15%. CoT may extract one or two saved instructions if
  there is a denser pattern adjacent in the model's training
  distribution; it is unlikely to surface fundamentally new
  structure that 200 + 65 dual_example samples failed to find.
- 7B-4bit is on the small end of modern coding models. The
  marketplace test — same harness, same prompts, same sort3
  problem, different (provider, model) pair on MacProvider — is
  the cleanest experiment to disambiguate model-capability from
  prompt-engineering as the binding constraint. It is exactly the
  arm64golf product story and is the next obvious step once a
  second (provider, model) is available on the network.

## Verdict

Current derived verdict: PASS-C.

## Run Evidence

- problem: `sort3-arm64`
- attempts: 74
- requested candidates: 592
- candidate responses: 273
- evaluated responses: 273
- verified evaluations: 111
- failed evaluations: 162
- evaluations with error text: 162
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

- 92x case 1 failed
- 43x case 2 failed
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
