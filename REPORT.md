# arm64golf v0.1 Report

Status: pass-c

## Phase 4 — marketplace canaries (2026-06-07)

Phase 4 ran two live MacProvider marketplace canaries on Pearl's clean default gateway and WebSocket timeout configuration. The Pearl VPS timeout experiment had already been reverted in Phase 1, so these runs exercised the shipped streaming path rather than a tuned environment.

| canary | provider | model | template | attempted | evaluations | verified | best verified | outcome |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Llama neutral | air8gb | `mlx-community/Llama-3.2-3B-Instruct-4bit` | `no_failed_context` (`c8c543c10e69293e`) | 25 requested; 16 ok, 9 `http_502` | 99 | 3 | 13 | First non-air5 leaderboard result; two distinct 13-instruction csel-tile hashes and one 15-instruction csel-tile hash. |
| Qwen hinted | air5 | `mlx-community/Qwen2.5-Coder-7B-Instruct-4bit` | `csel_hint` (`4d2ff188063962c5`) | 8 of 25 before watchdog kill | 36 | 35 | 12 | Signed attribution for the known score-12 csel-tile family; one score-16 new hash. |

The marketplace finding is now cleaner than the v0.3 framing. On the same neutral `no_failed_context` template, Qwen-Coder-7B has `best=None` and `0/4` verified while Llama-3.2-3B has `best=13` and `3/95` verified. The smaller Llama model surfaced csel-tile without an embedded hint; the larger Qwen-Coder model did not.

The corrected reading is not "csel is prompt-driven" in the broad sense. Within the two open-weight coder models we have data for, the prompt-elicitation threshold for the csel-tile structure varies by model. Qwen-Coder-7B reaches the known score-12 csel-tile family when the prompt embeds the pattern (`csel_hint`, and historically `dual_example`); Llama-3.2-3B surfaced csel-tile variants from the neutral `no_failed_context` prompt at this Phase 4's sample size. Whether csel-tile is broadly present across coder-model training corpora is not something this run establishes.

| pair | best verified | verified / evaluated | interpretation |
| --- | ---: | ---: | --- |
| air5 / Qwen-Coder-7B / `no_failed_context` | none | 0 / 4 | Neutral prompt did not elicit csel from Qwen-Coder-7B. |
| air8gb / Llama-3.2-3B / `no_failed_context` | 13 | 3 / 95 | Neutral prompt elicited two distinct 13-instruction csel-tile variants plus one 15-instruction variant. |
| air5 / Qwen-Coder-7B / `csel_hint` | 12 | 36 / 46 | Hint reliably elicits the known score-12 csel-tile structure; the Phase 4 partial canary supplied signed attribution. |
| air5 / Qwen-Coder-7B / `dual_example` | 12 | 56 / 158 | Historical hinted/example path remains consistent with the same csel-tile family. |

Infrastructure also moved from assumption to evidence. Across both canaries there were zero `stream_truncated` and zero `stream_idle_timeout` failures on Pearl's default 10s gateway/WS timeouts. The Phase 4 `pairs[]` aggregate populated end to end. Receipt v2 attestation populated end to end: the Llama receipts are the first real `kind='reference-harness'` v2 receipts in the wild for `no_failed_context`, signed with `template_id=c8c543c10e69293e`; the Qwen `csel_hint` receipts are signed with `template_id=4d2ff188063962c5`. The `--allow-marketplace-attribution` gate worked as intended: it allowed these explicitly requested marketplace pairs without weakening non-empty provider/model attribution.

Caveats:

- The Llama 13-instruction results are csel-tile family variations, not a new sub-12 structure: `055e012c82ee`, `4a8e7be0e09b`, and `3f846f0d8578` all tile the same 4-instruction `cmp/csel/csel/mov` compare-swap block with minor register-allocation or trailing-move variation.
- The Qwen `csel_hint` canary completed only 8 of 25 attempts before the environment watchdog killed it at about t+13min. The partial result is still informative because the deliverable was honest signed attribution for the known score-12 claim, and the partial run achieved that.
- The 9 `http_502` failures in the Llama canary are provider-side saturation on an 8GB Mac under sustained load. The harness classified them as gateway-level failures and did not retry-storm; they are not evidence of a code defect.
- The on-disk `57b2aa236342.json` receipt was upgraded from `legacy-v1-unknown` to `reference-harness` through the re-discovery plus `sign_receipt` overwrite path, so the leaderboard claim "`csel_hint` reaches 12" is now backed by signed evidence rather than legacy-v1-unknown attribution.

## Verdict

Current derived verdict: PASS-C.

## Run Evidence

- problem: `sort3-arm64`
- attempts: 123
- requested candidates: 984
- candidate responses: 463
- evaluated responses: 463
- verified evaluations: 149
- failed evaluations: 314
- evaluations with error text: 314
- best verified score: 12
- first verified response: 2
- first 17-instruction response: 115
- first 16-instruction response: 115
- near-best verified candidates: 4
- near-best unique opcode structures: 3

## Per-Pair Progress

| provider | model | template | template_id | evaluated | verified | best verified | first verified | first <=17 | first <=16 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| air5 | mlx-community/Qwen2.5-Coder-7B-Instruct-4bit | dual_example | 5d776fd84945be27 | 158 | 56 | 12 | 3 | 3 | 3 |
| air5 | mlx-community/Qwen2.5-Coder-7B-Instruct-4bit | csel_hint | 4d2ff188063962c5 | 46 | 36 | 12 | 10 | 10 | 10 |
| air8gb | mlx-community/Llama-3.2-3B-Instruct-4bit | no_failed_context | c8c543c10e69293e | 95 | 3 | 13 | 26 | 26 | 26 |
| air5 | mlx-community/Qwen2.5-Coder-7B-Instruct-4bit | failed_context | c151c941de808a4f | 105 | 54 | 18 | 2 | none | none |
| air5 | mlx-community/Qwen2.5-Coder-7B-Instruct-4bit | chain_of_thought | 6a47271645dc99d5 | 55 | 0 | none | none | none | none |
| air5 | mlx-community/Qwen2.5-Coder-7B-Instruct-4bit | no_failed_context | c8c543c10e69293e | 4 | 0 | none | none | none | none |

## Structural Diversity Evidence

- `f13bac4e5383f523`: 2 candidate(s), representative `57b2aa236342`, score 12, 12 instructions: `cmp csel csel mov cmp csel csel mov cmp csel csel mov`
- `9c4694538e3581d1`: 1 candidate(s), representative `4a8e7be0e09b`, score 13, 13 instructions: `cmp csel csel mov cmp csel csel mov cmp csel csel mov mov`
- `c2616ae59a133658`: 1 candidate(s), representative `055e012c82ee`, score 13, 13 instructions: `cmp csel csel mov mov cmp csel csel mov cmp csel csel mov`

This evidence is for manual PASS-C review only; automatic PASS-C still requires a verified 16-instruction candidate.

## Top Evaluation Errors

- 173x case 1 failed
- 84x case 2 failed
- 4x case 0 failed
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
