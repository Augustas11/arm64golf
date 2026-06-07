# arm64golf v0.1 PoC Specification

Status: private-test implementation ready; live air5 run pending
Owner: Augustas11
License: MIT
Harness language: Python 3.11+
Primary problem: `sort3-arm64`
Primary model: `mlx-community/Qwen2.5-Coder-7B-Instruct-4bit`
Primary provider: `air5`

## 1. Goals And Non-goals

### 1.1 Mission

`arm64golf` is a public research project where open-weight coding models,
served by the MacProvider network, search for shorter ARM64 assembly routines
than published references for fixed-size sort and hash problems.

v0.1 is intentionally small:

- one problem: `sort3-arm64`
- one inference path: MacProvider `air5`
- one model: `mlx-community/Qwen2.5-Coder-7B-Instruct-4bit`
- one verifier: deterministic local sandboxed checking
- one attestation primitive: ed25519 signed receipts per verified candidate
- one eventual public surface: a static leaderboard, private during testing

### 1.2 PoC Questions

The proof of concept exists to answer exactly three questions:

1. Can a 7B open-weight coder model, served from a 16GB MacBook Air (air5)
   on the MacProvider network, propose **correct** ARM64 assembly mutations?
2. Starting from a textbook 18-instruction ARM64 `sort3`, can the search loop
   **rediscover** a 17-instruction variant (matching AlphaDev's x86 record)?
3. Does the loop expose any **frontier signal** -- i.e. is the search dynamic
   informative enough to suggest a 16-instruction variant might be reachable?

### 1.3 AlphaDev Context

Google DeepMind's AlphaDev optimized assembly-level sorting routines for x86
using a reinforcement-learning assembly game. The Nature paper states that the
work focuses on a subset of x86 instructions and reports shorter fixed-sort
algorithms for sort 3 and sort 5 while matching the state of the art for sort
4. The public `google-deepmind/alphadev` repository reports:

- `Sort3AlphaDev`: 17 instructions
- `Sort4AlphaDev`: 28 instructions
- `Sort5AlphaDev`: 43 instructions

Those are x86 numbers only. They are narrative and scoring context for this
project, not ARM64 baselines and not proof of an ARM64 optimum.

### 1.4 Goals

- Build a clean, standalone repository for ARM64 routine search. The test phase
  uses a private GitHub repo; public release happens only after explicit launch
  approval.
- Verify ARM64 candidates locally and deterministically before scoring them.
- Attribute every verified candidate to the exact model and provider that
  produced it.
- Publish leaderboard data in a form inspectable without trusting a private
  database.
- Make the README useful as a recruiting page for MacProvider providers.

### 1.5 Non-goals

- No claim about deployment to libc, libc++, compiler runtimes, or any real
  standard library. That is v2+.
- No multi-problem leaderboard in v0.1.
- No public contestant submission intake in v0.1.
- No multi-provider or k-of-n attestation in v0.1.
- No model fine-tuning.
- No MLX runtime inside this harness.
- No modification of `/Users/augstar/macprovider-poc/`.
- No import of MacProvider coordinator or gateway code as a module.
- No git submodule relationship with MacProvider.

## 2. Module Interface

### 2.1 Problem Directory

A research problem is a directory under `problems/`. The first problem is:

```text
problems/sort3-arm64/
```

Future problems should be swappable without changing the search loop's core
control flow.

### 2.2 Required Files

Each problem directory contains:

```text
module.toml
module.py
reference.s
tests.json
```

Problem-specific helpers are allowed, but the search harness may only depend
on the module interface.

### 2.3 Required Functions

A problem module implements four functions:

```python
def baseline() -> tuple[int, str]:
    ...

def load(submission_blob: str) -> Candidate:
    ...

def verify(candidate: Candidate) -> bool:
    ...

def score(candidate: Candidate) -> int:
    ...
```

`baseline()` returns the canonical reference instruction count and assembly.
`load()` materializes a model submission into a runnable candidate artifact.
`verify()` runs deterministic correctness checks and returns a boolean.
`score()` returns the instruction count used for ranking.

### 2.4 Candidate Contract

The shared candidate object includes:

- `problem_id`
- `source`
- `normalized_source`
- `candidate_hash`
- `instruction_count`
- `metadata`

`candidate_hash` is the lowercase SHA-256 digest of normalized source bytes.
`instruction_count` counts executable ARM64 instructions after removing blank
lines, comments, labels, and assembler directives.

### 2.5 `module.toml`

Every problem declares:

```toml
problem_id = "sort3-arm64"
license = "MIT"

[hardware]
arch = "arm64"
os = "macos"

[eval]
time_budget_ms = 100
memory_budget_mb = 256
min_tests = 1000

[sandbox]
profile = "../../sandbox/profile.sb"
filesystem = "deny"
network = "deny"
process_spawn = "deny"
```

The schema captures the minimum swap cost for future modules: hardware
requirements, time and memory budget per candidate, sandbox profile, and
license.

### 2.6 Harness Boundary

The search harness owns inference, retry policy, persistence, receipt
issuance, and leaderboard export. The problem module owns parsing,
canonicalization, deterministic correctness checks, and score calculation.

## 3. First Module: `sort3-arm64`

### 3.1 Problem Statement

Sort three signed 64-bit integers in ARM64 registers.

Canonical register ABI for v0.1:

- input: `x0`, `x1`, `x2`
- output: sorted ascending values in `x0`, `x1`, `x2`
- clobbers: `x3` through `x8` are allowed
- memory: not allowed for the candidate routine body
- branches: not allowed for v0.1 candidates

The no-memory and no-branch constraints keep the search focused on a
branchless register routine comparable in spirit to AlphaDev's fixed-sort
setting.

### 3.2 Baseline

The reference baseline is an 18-instruction textbook ARM64 `sort3` generated
from a naive C implementation compiled with:

```bash
clang -O3 -S -target aarch64-apple-darwin
```

The generated assembly is hand-cleaned to a stable canonical form and
committed as `problems/sort3-arm64/reference.s`. The baseline is a starting
point, not a claimed optimum.

### 3.3 Target

The v0.1 target is to match AlphaDev's x86 `Sort3AlphaDev` count at 17
instructions and probe for a 16-instruction verified ARM64 candidate.

A 17-instruction ARM64 result should be described as matching AlphaDev's x86
sort3 instruction count on ARM64, not as proving superiority over AlphaDev.
A 16-instruction result must be verified before any headline is written.

### 3.4 Test Set

`tests.json` contains at least 1000 fixed input triples and expected sorted
outputs.

The test set must include zero, positive values, negative values, duplicates,
already sorted triples, reverse sorted triples, min/max signed 64-bit values,
and deterministic pseudo-random triples.

### 3.5 Correctness Rule

A candidate passes when every test case returns exactly the expected sorted
triple.

Undefined behavior is not allowed: no memory reads or writes, no external
calls, no system calls, no process creation, no network, and no reliance on
uninitialized registers outside the declared inputs.

## 4. Inference Path

### 4.1 Endpoint

The harness calls the MacProvider OpenAI-compatible endpoint:

```text
POST https://api.streamvc.live/v1/chat/completions
```

### 4.2 Model Pin

The model is pinned to:

```text
mlx-community/Qwen2.5-Coder-7B-Instruct-4bit
```

The harness must not silently switch to another model. Incorrect model attribution poisons the leaderboard.

Phase 4 marketplace runs use `--allow-marketplace-attribution` to opt in to non-v0.1 `(provider, model)` pairs; the gate still requires both fields, records the pair verbatim in receipts and `pairs[]`, and keeps reference-harness attribution (`pairs[].attribution_kind: "reference_harness"`; receipt kind: `"reference-harness"`).

### 4.3 Provider Pin

The provider is pinned through:

```text
X-MacProvider-Provider: air5
```

The sibling MacProvider legacy provider file currently uses `m4` as the provider key for the M4 Mac endpoint. `arm64golf` uses `air5` as the intended public attribution string unless the operator handoff proves that the live coordinator requires a different provider id.
If the live id differs, document the mapping in `AIR5_OPERATOR_NOTE.md` and receipts before running the search.

### 4.4 Request Shape

The request body follows OpenAI chat-completions shape and must request SSE
streaming:

```json
{
  "model": "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "temperature": 0.7,
  "top_p": 0.95,
  "n": 1,
  "max_tokens": 256,
  "stream": true
}
```

The harness configuration still defaults to `"n": 8` candidate responses per
round, but the MacProvider gateway rejects `n > 1`, so the client fans that out
into sequential single-completion requests with `n: 1`.

Authentication uses the operator's MacProvider API key.

### 4.5 Failure Modes

v0.2 switches the success path to SSE streaming for the clean-default-config
canary: a 10s gateway header timeout and a 10s WebSocket write timeout, without
operator-specific timeout tuning. The client still keeps bounded streaming
guards: `stream_total_timeout_s` defaults to 60s, `stream_idle_timeout_s`
defaults to 10s, `stream_max_bytes` defaults to 4 MiB, and
`stream_max_line_bytes` defaults to 64 KiB.

Streaming failures use stable attempt kinds. `stream_idle_timeout` means the
server was reachable but stopped making line progress; `stream_truncated` means
the stream exceeded total/byte/line bounds or ended before `data: [DONE]`;
top-level in-band SSE `error` chunks become quota/burst errors when their code
matches those classes, or `server_error` for other upstream error codes.

Provider offline:

- record an attempt failure
- back off
- do not switch provider

Model not loaded:

- record a model-unavailable failure
- stop or back off pending operator action
- do not substitute the non-coder Qwen model

HTTP timeout:

- retry with exponential backoff
- cap retries per round
- preserve attempt metadata

Malformed response:

- record parse failure
- continue to next response when possible

Stream truncated:

- record a `stream_truncated` attempt failure
- continue the client-side fan-out when possible
- keep it distinct from malformed response parsing

Rate limit:

- respect `Retry-After` when present
- otherwise back off conservatively

Authentication failure:

- stop the run
- do not write leaderboard promotions from unauthenticated attempts

## 5. Search Loop

### 5.1 Strategy

v0.1 uses a tight rewrite-and-verify loop:

1. Load the current best candidate.
2. Ask the model for a one-instruction-shorter variant.
3. Extract assembly only.
4. Load and normalize the candidate.
5. Verify in the sandbox.
6. Score by instruction count.
7. Record the attempt.
8. Sign a receipt for verified candidates.
9. Promote if the score improves.
10. Export static leaderboard JSON.

### 5.2 Population

Population size is 1. There is no evolution, crossover, archive sampling, or
FunSearch-style program synthesis in v0.1.

### 5.3 Sampling

Default sampling:

- temperature: `0.7`
- top_p: `0.95`
- candidates per round: `8`

### 5.4 Prompts

The main prompt template:

```text
Here is the current best ARM64 routine for sort3 (N instructions).
Propose a variant with N-1 instructions that still produces sorted output.
Output ONLY the assembly, no commentary.
```

Ablation templates may vary whether failed mutations are included, whether
verifier error categories are included, and whether no-branch/no-memory
constraints are emphasized. The harness records the template for each
candidate.

### 5.5 Attempt Accounting

The store tracks both HTTP request attempts and returned candidate responses.
For v0.1 PASS/FAIL thresholds, one counted inference unit is one candidate
response evaluated by the verifier. `attempt_count` records HTTP requests;
`candidate_response_count` records the threshold counter.

The live harness defaults to a 10,000 candidate-response cap. It continues
after PASS-A so the same run can still probe for PASS-B/PASS-C, and stops by
default when the derived verdict reaches PASS-B, PASS-C, or FAIL.

## 6. Sandbox

### 6.1 Requirement

No untrusted assembly may execute outside a hardened sandbox profile. This is
a hard v0.1 requirement, not a future improvement.

### 6.2 Execution Location

Candidate execution happens on the operator machine running the harness.
`air5` serves inference only. It does not execute candidate assembly in v0.1.

### 6.3 macOS Sandbox

The runner uses macOS `sandbox-exec` with a deny-by-default profile at
`sandbox/profile.sb`.

The profile denies filesystem access except explicitly allowed temporary
execution artifacts, network access, process creation, and unauthorized
syscalls.

### 6.4 Caps

Each candidate run has a 100 ms wall-clock cap, a 256 MB address/data memory
cap, and bounded stdout/stderr capture. The generated verifier executable arms
the memory cap and interval timer before calling the candidate routine.

### 6.5 Sandbox Tests

Pytest coverage must confirm the sandbox blocks filesystem reads, filesystem
writes, network access, fork/process spawn, and exec of external programs from
inside the sandbox.

If `sandbox-exec` is unavailable on a host, tests must mark that limitation
explicitly. The project may not claim verified candidate execution on that
host.

## 7. Receipt Format

### 7.1 Key Material

The harness generates an ed25519 keypair on first run.

Private key:

```text
data/sign.key
```

Public key:

```text
receipts/PUBKEY
```

`data/sign.key` is gitignored. `receipts/PUBKEY` is committed.

### 7.2 Payload

Each verified candidate receives one receipt. The signed payload is
deterministic JSON with sorted keys and compact separators:

```json
{
  "attestation": {
    "kind": "reference-harness",
    "details": {
      "template_id": "4d2ff188063962c5",
      "template_name": "csel_hint",
      "temperature": 0.7,
      "top_p": 0.95,
      "n": 8
    }
  },
  "candidate_hash": "sha256...",
  "harness_version": "0.2.0",
  "model_id": "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
  "problem_id": "sort3-arm64",
  "provider_id": "air5",
  "score": 18,
  "ts": "2026-06-05T00:00:00Z"
}
```

### 7.3 Envelope

The receipt file stores:

```json
{
  "payload": {},
  "signature": "base64-ed25519-signature",
  "public_key": "base64-ed25519-public-key"
}
```

### 7.4 Compatibility With MacProvider Trust Idiom

The shape mirrors the MacProvider trust idiom: deterministic identity fields,
explicit provider id, hash-bound artifact, timestamp, short public display
prefixes, and a signature verified independently of the database.

The implementation is clean-room. It must not import MacProvider Go code.

### 7.5 Attestation

Receipt payload v2 adds an `attestation` object for producer metadata while
keeping v1 identity, score, timestamp, and signature semantics intact. Its
shape is:

```json
{
  "kind": "reference-harness",
  "details": {}
}
```

`kind` is a stable string discriminator. `details` is a kind-specific object.
Known v2 kinds:

- `seed-baseline`: receipt emitted for the local reference baseline.
  `details` MUST be `{}`.
- `reference-harness`: receipt emitted from a model-derived run through the
  closed reference harness. `details` MUST contain `template_id`,
  `template_name`, `temperature`, `top_p`, and `n`.
- `legacy-v1-unknown`: upgraded v1 receipt whose original producer provenance
  is no longer authoritatively known. It is not a seed baseline and not a fully
  attested reference-harness run. `details` MUST be `{}`.
- `mock`: receipt emitted from `--mock-response-file` offline smoke input.
  `details` MUST be `{}`.

Verifiers MUST accept unknown `kind` values in the signed payload when
`details` is a JSON object. This keeps the v2 receipt format forward-compatible
with Stage C and other future producer classes. Stage C will introduce
`kind: "open-submission"` in a future PR; the receipt format does not change.
Stage C may add stricter validation for that kind.

For every kind, the canonical JSON form of `details` encoded as UTF-8 MUST be
no more than 4096 bytes. This preserves forward-compatible unknown kinds while
keeping receipt signing and verification bounded.

For `reference-harness`, `template_id` is the 16-hex sha256 prefix of the
template body. The `chain_of_thought` template is a special case: its
`template_id` hashes `COT_SYSTEM_PROMPT` concatenated with the template body
because that template changes both system and user prompt content.

## 8. Leaderboard Schema

### 8.1 Scope

The v0.1 leaderboard has one problem: `sort3-arm64`.

### 8.2 Columns

Columns:

- rank
- score
- candidate_hash
- model_id
- provider_id
- receipt_signature
- discovered_at

Display-friendly variants may shorten hashes and signatures, but the static
JSON export preserves full values.

Summary fields:

- `attempt_count`: number of harness request attempts recorded
- `requested_candidate_count`: total completions requested from the model
- `candidate_response_count`: total completion choices returned and evaluated
- `run_summary`: derived run evidence, including evaluated responses,
  verified evaluations, best verified score, and first response ordinals for
  verified, 17-instruction, and 16-instruction candidates. It also includes
  failed evaluation count, error-bearing evaluation count, and top grouped
  evaluation errors for FAIL-mode analysis. For manual PASS-C review, it
  includes near-best verified candidate count, near-best unique opcode
  structure count, and representative opcode-sequence fingerprints.

PASS/FAIL reporting uses `candidate_response_count` for the "within 200" and
"within 10,000" thresholds, with `requested_candidate_count` retained to show
provider shortfall or failed requests.

The SQLite store also records each evaluated response in `evaluations`; this
preserves score, verified status, and sandbox/compiler error text even when
multiple responses deduplicate to the same candidate hash.

### 8.3 Static Export

The harness writes:

```text
web/public/leaderboard.json
```

The web page reads that file directly.

KISS deployment for v0.1:

1. harness writes static JSON every N attempts
2. operator commits and pushes
3. Vercel rebuilds

There is no live API in v0.1.

`bin/summarize-run.py` reads the SQLite store and emits a deterministic
summary/verdict from the recorded attempts and evaluations. `bin/write-report.py`
uses the same evidence to regenerate `REPORT.md`. PASS-C from a verified
16-instruction candidate is automatic; PASS-C from structural diversity remains
a manual review item backed by the near-best structural fingerprints in
`run_summary`.

Before preview, launch, or a live search run, the operator validates the static
surface with `bin/validate-web.py`, validates every leaderboard row against its
signed receipt with `bin/validate-receipts.py`, audits BUILD_PROMPT
deliverables with `bin/audit-deliverables.py`, and uses `bin/ready-live-run.py`
as the aggregate readiness gate. The readiness gate is intentionally
conservative: it must report no blockers in the operator environment before a
live search starts.

### 8.4 Pairs Summary

The top-level leaderboard JSON also includes `pairs`, a list of aggregate
progress rows for the current problem. Each row summarizes evaluated responses
for one provider/model attribution group and has this schema:

- `problem_id`
- `provider_id`
- `model_id`
- `template_name` (`string | null`)
- `template_id` (`string | null`)
- `attribution_kind` (`reference_harness | open_submission | mock`)
- `evaluated_responses`
- `verified_count`
- `best_verified_score`
- `first_verified_response`
- `first_17_response`
- `first_16_response`

Rows with `attribution_kind: "reference_harness"` MUST have non-null
`template_name` and `template_id`; `template_id` is derived with
`harness.prompts.template_id(template_name)`, and legacy template names that are
no longer in the template registry are skipped. Rows with `open_submission` or
`mock` attribution MUST set both template fields to null.

The aggregate is derived from `evaluations` joined through `attempts` for
template attribution and `candidates` for provider/model/problem attribution.
When the exporter reaches the 256-row `pairs` cap, the top-level leaderboard
JSON includes the sibling field `pairs_truncated: true`; otherwise the field may
be omitted.

Seed-baseline entries are excluded from `pairs`: the local seed is not a model
search attempt and has no prompt template. The exporter excludes both explicit
`seed-baseline` attempts and `reference-baseline` candidate attribution so old
and current ledgers do not inflate per-pair response counts.

## 9. Success Criteria

### 9.1 PASS-A: Translation Works

Within 200 evaluated candidate responses, the harness produces at least one
syntactically valid ARM64 assembly candidate that passes the sandboxed verifier
on all 1000+ test inputs.

This proves Qwen2.5-Coder-7B can generate correct ARM64 at all in this setup.

### 9.2 PASS-B: Rediscovery

Within 10,000 evaluated candidate responses, the harness finds a
17-instruction ARM64 `sort3` candidate that passes verification.

This matches AlphaDev's x86 `sort3` instruction count on ARM64. It does not
prove ARM64 optimality unless separately established.

### 9.3 PASS-C: Frontier Signal

After PASS-B, PASS-C is reached if either at least one 16-instruction
candidate verifies, or near-best candidates show non-trivial structural
diversity.

Structural diversity may include distinct instruction sequences, temporary
register strategies, or compare/swap decompositions among verified or nearly
verified candidates.

### 9.4 FAIL

If none of PASS-A, PASS-B, or PASS-C is reached within 10,000 evaluated
candidate responses, the project reports FAIL.

FAIL is useful when documented clearly. `REPORT.md` must identify observed
failure modes such as invalid assembly, wrong ABI assumptions, trivial
permutations only, verifier mismatch, sandbox constraints too tight, or
provider/model availability problems.

### 9.5 Report

`REPORT.md` is written at the end of the run regardless of outcome.

It includes final verdict, candidate-response count, best candidate score,
best candidate hash, receipt links for verified candidates, failure-mode
summary when applicable, limits, and next steps.

## 10. Out Of Scope

### 10.1 Multi-problem Leaderboard

v0.1 is `sort3-arm64` only. Future candidates include `sort4-arm64`,
`sort5-arm64`, hash kernels, and fixed-size memcmp-style kernels.

### 10.2 Multi-provider Attestation

v0.1 trusts a single operator-run harness. k-of-n receipt agreement across
provider Macs is v0.2+.

### 10.3 Public Contestants

v0.1's only contestant is the harness itself. Public submission intake is
v0.2+.

### 10.4 Fine-tuning

The model is used as-is. No finetuning, LoRA, preference optimization, or
training data pipeline is in scope.

### 10.5 Evolution

There is no population evolution in v0.1. The loop is direct mutation with
population size 1.

### 10.6 Closed-model Comparison

v0.1 is open-weight only by design. No comparison against frontier closed
models belongs in the launch claim.

## References

- Google DeepMind AlphaDev repository:
  <https://github.com/google-deepmind/alphadev>
- Nature: "Faster sorting algorithms discovered using deep reinforcement
  learning", Nature 618, 257-263 (2023):
  <https://www.nature.com/articles/s41586-023-06004-9>
- MacProvider repository:
  <https://github.com/Augustas11/macprovider>
