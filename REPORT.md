# arm64golf v0.1 Report

Status: pass-c

## Network configuration this canary depended on

The v0.3 canary and the v0.3 post-canary probes (csel_hint,
dual_example, temperature sweep, chain_of_thought at 512 and 1024
max_tokens) all ran against production MacProvider at
api.streamvc.live, with the following non-default config in effect:

- `gateway.timeouts.coordinator_header_timeout_seconds: 60` (default: 10;
  bumped 2026-06-05 because a 10s ceiling truncated any non-streaming
  inference exceeding 10s of generation).
- `coordinator.ws.write_timeout_s: 60` (default: 10; same reason).
- `gateway.quotas.account_daily_tokens: 20000000` (default: 100000;
  default was insufficient for a single 200-call canary).

These were operator config changes made during v0.1 / v0.2 sessions
to unblock the canary; they remain in effect on Pearl VPS
(159.223.165.194) as the network's standing config. A future "clean
default config" canary would need to either run with non-default
timeouts, switch to streaming, or restrict the workload to fit the
defaults.

The v0.3 harness adds its own bound on the buyer side
(`InferenceConfig.max_tokens=256` by default, bumped to 1024 for the
CoT probes to give the model room for reasoning + a final fenced
code block).

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
  three cmp + csel + csel + mov blocks.

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

## Search Discovery — closing the 7B chapter

The post-canary probes test progressively stronger versions of "can
the model find denser structure without the answer being handed
over." Final tally:

| probe | template | new evals | verified | unique new hashes | best score |
|---|---|---|---|---|---|
| csel_hint | csel_hint @ temp=0.7 | 10 | 1 | +1 (12) | 12 |
| dual_example | dual_example @ temp=0.7 | 93 | 21 | +2 (12 variant, redundant 16) | 12 |
| temp sweep | dual_example × {0.3, 0.5, 0.9} | 65 | 35 | +0 | 12 |
| CoT @ 512 | chain_of_thought, max_tokens=512 | 25 | 0 | +0 (model token-starved, never reached the final code block) | — |
| CoT @ 1024 | chain_of_thought, max_tokens=1024 | 30 | 0 | +0 (model emits valid code but routines fail edge cases) | — |

Across 5 probes / 223 new evaluations after the v0.3 canary, only
two unique verified hashes appeared — both at score 12, both
csel-tile variants (`57b2aa236342` with `le`, `b4d6f989140e` with
`lt`). Zero candidates below 12. Zero new structures.

**The CoT regression is the most diagnostic result.** With enough
token budget for the model to actually complete its reasoning
(max_tokens=1024), the model reaches the final fenced code block
in 27 of 30 attempts and the extractor parses valid assembly. But
0 of those 30 routines verify. The dominant failure modes flip
from the csel-hint-driven probes (where verified rate was high and
errors were mostly ISA pitfalls) to **20× case-2 failed
(already-ascending input) + 7× case-1 failed (all-equal triple)**.
The model is "reasoning" itself out of correct routines: it
identifies the third comparator as "redundant with the first"
(plausible-looking but wrong — that comparator is what guarantees
correctness on the already-sorted case) and removes it.

This is a classic small-model CoT regression. The explicit
step-by-step prose lets the model talk itself into eliminating
load-bearing instructions that the implicit-pattern prompts left
alone.

**Updated prior on the prompt-vs-model question:** post-CoT,
roughly **92/8 model.** CoT — the strongest prompt-sophistication
lever — didn't unlock new structure and actively regressed verified
output. The prompt-engineering door is closed on 7B with high
confidence.

**For Qwen2.5-Coder-7B-Instruct-4bit on this sort3 problem under
arm64golf's prompt family + sampling + reasoning experiments:**

- The model has exactly two sort3 routines in its working
  repertoire: 18-instruction bitmask-eor (the baseline shape) and
  12-instruction csel.
- The 12-instruction pattern fires only when the prompt explicitly
  names it.
- More sampling, different temperatures, and chain-of-thought
  reasoning all fail to surface a sub-12 routine. CoT makes the
  model worse, not better.
- Any further compression on this problem requires a different
  model.

The clean next experiment is the marketplace test — same harness,
same prompts, different (provider, model) pair on MacProvider.
That is exactly the arm64golf product story (showing how the
marketplace surfaces the cost/quality Pareto frontier for a
concrete optimization problem) and is the next obvious step once a
second (provider, model) is available on the network.

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
- 1x /private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:6:5: error: unexpected token at start of statement
    1. **Block 1**: `cmp x0, x1 / csel x3, x1, x0, le / csel x0, x0, x1, le / mov x1, x3`
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:7:5: error: unexpected token at start of statement
    - **Comparison**: `x0 <= x1`
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:8:5: error: unexpected token at start of statement
    - **Reads**: `x0, x1`
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:9:5: error: unexpected token at start of statement
    - **Mutates**: `x0, x1, x3`
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:10:5: error: unexpected token at start of statement
    - **Untouched**: `x2`
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:11:5: error: unexpected token at start of statement
    - **Necessary**: Yes, ensures `x0 <= x1` before further comparisons.
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:12:5: error: unexpected token at start of statement
    2. **Block 2**: `cmp x1, x2 / csel x3, x2, x1, le / csel x1, x1, x2, le / mov x2, x3`
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:13:5: error: unexpected token at start of statement
    - **Comparison**: `x1 <= x2`
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:14:5: error: unexpected token at start of statement
    - **Reads**: `x1, x2`
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:15:5: error: unexpected token at start of statement
    - **Mutates**: `x1, x2, x3`
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:16:5: error: unexpected token at start of statement
    - **Untouched**: `x0`
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:17:5: error: unexpected token at start of statement
    - **Necessary**: Yes, ensures `x1 <= x2` before further comparisons.
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:18:5: error: unexpected token at start of statement
    3. **Block 3**: `cmp x0, x1 / csel x3, x1, x0, le / csel x0, x0, x1, le / mov x1, x3`
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:19:5: error: unexpected token at start of statement
    - **Comparison**: `x0 <= x1`
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:20:5: error: unexpected token at start of statement
    - **Reads**: `x0, x1`
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:21:5: error: unexpected token at start of statement
    - **Mutates**: `x0, x1, x3`
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:22:5: error: unexpected token at start of statement
    - **Untouched**: `x2`
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:23:5: error: unexpected token at start of statement
    - **Necessary**: No, redundant with Block 1.
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:25:19: error: unexpected token in argument list
    The redundant block is Block 3, which is identical to Block 1 and does not add any new information or necessary operations. This block can be eliminated.
                  ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:27:5: error: invalid character in input
    ```arm64
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:27:5: error: unexpected token at start of statement
    ```arm64
    ^
/private/tmp/arm64golf-sandbox/run-0mrgmscm/candidate.s:35:5: error: too few operands for instruction
    mov
    ^~~
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
