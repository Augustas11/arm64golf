# Build prompt — `arm64golf` v0.1 (PoC)

Operator-paste prompt to bootstrap `arm64golf` — a public-facing research
leaderboard where open-weight LLMs served by the MacProvider network search
for shorter ARM64 sort/hash routines than published baselines. v0.1 is a PoC
sized to validate three questions in 7–10 days:

1. Can a 7B open-weight coder model, served from a 16GB MacBook Air (air5)
   on the MacProvider network, propose **correct** ARM64 assembly mutations?
2. Starting from a textbook 18-instruction ARM64 `sort3`, can the search loop
   **rediscover** a 17-instruction variant (matching AlphaDev's x86 record)?
3. Does the loop expose any **frontier signal** — i.e. is the search dynamic
   informative enough to suggest a 16-instruction variant might be reachable?

The PoC ships as a public GitHub repo + public leaderboard subdomain because
the GTM thesis is: **the leaderboard is the recruiting magnet** for the next
wave of MacProvider providers. A spike that lives in a terminal doesn't
recruit anyone.

Paste everything between `=== BEGIN PROMPT ===` and `=== END PROMPT ===`
into a fresh session rooted at `/Users/augstar/arm64golf` (which exists but
is empty). Read the locked context section first; do not start writing code
until the spec doc (Phase 1) is committed.

---

```
=== BEGIN PROMPT ===

You are bootstrapping `arm64golf`, a new public research project that lives
as a sibling repo to `Augustas11/macprovider` under the same GitHub owner.
arm64golf is NOT inside the macprovider tree, does NOT import macprovider as
a module, and does NOT modify macprovider's audited money-path code. The
only tether is: arm64golf consumes LLM inference from MacProvider's network
(specifically the provider node `air5`), and its signed-receipt format is
shape-compatible with MacProvider's receipt pattern so the two systems share
a trust idiom.

## Mission (1 paragraph)

Build a public leaderboard where open-weight coding models, served by the
MacProvider network, search for shorter ARM64 assembly routines than
published references for fixed-size sort and hash problems. v0.1 ships ONE
problem (`sort3-arm64`), ONE inference path (air5 serving
Qwen2.5-Coder-7B-Instruct-4bit), and ONE attestation primitive (ed25519
signed receipts per verified candidate). The repo's README doubles as a
recruiting page for new MacProvider providers — every UI surface tells the
"open-weight models on Apple Silicon vs DeepMind's x86 AlphaDev" story.

## Why this exists (context the executor needs)

- **MacProvider** is a network of Apple Silicon Macs serving MLX inference,
  OpenAI-compatible API. Live at `console.streamvc.live`. Provider node
  `air5` is the M4 MacBook Air (16 GB unified memory) currently serving
  `mlx-community/Qwen2.5-7B-Instruct-4bit`. For this PoC, air5's operator
  will swap to `mlx-community/Qwen2.5-Coder-7B-Instruct-4bit` (better at
  code, same memory footprint at 4-bit). The swap is a separate handoff
  documented in Phase 8 below; do not assume it has happened until verified.
- **AlphaDev** (DeepMind, Nature 2023) discovered shorter x86 sort routines
  using RL+MCTS; results merged into LLVM libc++. Their published numbers
  are for x86. ARM64 is a different ISA with different optima and no
  comparable published frontier — that is the gap arm64golf targets.
- **The GTM thesis**: the PoC's public leaderboard is the recruiting magnet
  for the next wave of MacProvider providers. Every artifact should be
  publishable, attestable, and provider-attributed.

## Locked context (READ BEFORE WRITING)

You are root in `/Users/augstar/arm64golf` (empty directory). Read these
files in the sibling `macprovider-poc` tree to understand conventions; do
NOT modify them:

1. `/Users/augstar/macprovider-poc/README.md` — MacProvider overview
2. `/Users/augstar/macprovider-poc/CLAUDE.md` — repo conventions, git
   identity rules (arm64golf is a DIFFERENT repo; gh identity rules differ —
   see Phase 0)
3. `/Users/augstar/macprovider-poc/beta/web/api/providers.js` — current
   provider directory (confirms air5 / m4 endpoint shape)
4. `/Users/augstar/macprovider-poc/phase4-coordinator/internal/auth/tokens.go`
   — token store pattern (arm64golf will mirror the ed25519 idiom, NOT
   import this code)
5. `/Users/augstar/macprovider-poc/phase5-gateway/internal/router/server.go`
   — OpenAI-compatible request shape arm64golf will call (skim only)
6. AlphaDev paper / GitHub (`google-deepmind/alphadev`) — confirm x86
   sort3 / sort4 / sort5 baseline instruction counts; note explicitly that
   ARM64 has no published equivalent

## What MUST NOT happen

- No modification of any file under `/Users/augstar/macprovider-poc/`. arm64golf
  is independent.
- No `git submodule` linking the two repos. They are siblings, period.
- No import of `phase4-coordinator` or `phase5-gateway` Go code as a module.
  Cleanroom-mirror receipt format only.
- No claim in README/leaderboard that exceeds what the PoC actually proves.
  If we rediscover 17-instruction sort3, the headline is "rediscovered
  AlphaDev's x86 record on ARM64." If we find 16, the headline is bigger.
  Do not pre-write headlines for results we haven't achieved.
- No execution of untrusted assembly outside a hardened sandbox profile.
  The sandbox is a hard requirement, not a future improvement.

## What to build — phased

### Phase 0: Repo bootstrap

- `git init` in `/Users/augstar/arm64golf`
- `LICENSE` — MIT
- `.gitignore` — Python (`__pycache__/`, `.venv/`, `*.pyc`), Node
  (`node_modules/`, `.next/`), OS junk, `*.sqlite`, `data/`, `receipts/`,
  `.env*`
- `README.md` — see Phase 1 for content requirements
- Create the GitHub repo: `gh repo create Augustas11/arm64golf --public
  --source=. --remote=origin --description "Open-weight coding models on
  Apple Silicon search the ARM64 sort/hash frontier. Powered by MacProvider."`
  Use the `Augustas11` gh account (NOT `antfleet-ops`). If `gh auth status`
  shows `Augustas11` is not active, run `gh auth switch -u Augustas11`
  first — arm64golf does NOT inherit macprovider's per-repo credential
  helper.
- First commit: `chore: bootstrap arm64golf`, push to `main`.

### Phase 1: Spec doc and README

`SPEC.md` — the PoC definition, ~300–600 lines, sections:

- **§1 Goals & non-goals.** Three PoC questions verbatim from the top of
  this prompt. Non-goal: any claim about deployment to real stdlib (that's
  v2+).
- **§2 Module interface.** A "research problem" in arm64golf is a directory
  under `problems/` implementing four functions:
  - `baseline()` returns the published reference instruction count and the
    canonical reference assembly
  - `load(submission_blob) → Candidate` materialises a submission into a
    runnable artifact
  - `verify(Candidate) → bool` runs deterministic correctness check
  - `score(Candidate) → int` returns instruction count
  Plus a `module.toml` declaring: hardware requirements, time budget per
  eval, sandbox profile, license. This is the swap-cost minimum for future
  modules.
- **§3 First module: `sort3-arm64`.** Sort 3 int64s in registers. Reference
  baseline: 18-instruction textbook ARM64 (you generate this from a naive
  C `sort3` compiled with `clang -O3` for `aarch64-apple-darwin`, hand-
  cleaned to a stable canonical form, committed under
  `problems/sort3-arm64/reference.s`). Target: match AlphaDev's x86 17,
  probe for 16.
- **§4 Inference path.** OpenAI-compatible calls to
  `https://api.streamvc.live/v1/chat/completions`, model pinned to
  `mlx-community/Qwen2.5-Coder-7B-Instruct-4bit`, provider pinned to `air5`
  via `X-MacProvider-Provider: air5` header. Document the failure modes
  (provider offline, model not loaded, etc.) and the loop's behavior in
  each case (back off, log, do not silently switch models — incorrect
  model attribution would poison the leaderboard).
- **§5 Search loop.** Tight rewrite-and-verify loop: present current best,
  ask for a 1-instruction-shorter variant, verify, score, record. Population
  size 1 for v0.1 (no evolution yet). Sampling: temperature 0.7, top_p 0.95,
  N=8 candidates per round.
- **§6 Sandbox.** macOS `sandbox-exec` profile, no syscalls except those
  needed for the assembled routine to run on its inputs. Wall-clock cap
  100 ms per candidate run. Memory cap. No FS, no network. v0.1 runs on
  one operator machine, NOT on air5 — air5 only serves inference. (Future:
  k-of-n attestation across multiple provider Macs. Out of scope here.)
- **§7 Receipt format.** ed25519 signature over deterministic JSON of
  `{problem_id, candidate_hash, score, model_id, provider_id, harness_version, ts}`.
  Public key published in `receipts/PUBKEY`. One receipt per verified
  candidate. Format shape-compatible with MacProvider's pattern (read
  `phase4-coordinator/internal/auth/tokens.go` for the shape idiom; do NOT
  import).
- **§8 Leaderboard schema.** Single problem v0.1. Columns: rank, score
  (instructions), candidate_hash (short), model+provider attribution,
  receipt_signature (short), discovered_at.
- **§9 Success criteria.** Explicit thresholds for translation /
  rediscovery / frontier (see Success Criteria below).
- **§10 Out of scope.** Multi-problem, multi-provider attestation, model
  evolution, fine-tuning, contestant submissions (this v0.1 has ONE
  contestant: the harness itself).

`README.md` — public-facing, doubles as recruiting page. Structure:
- Hero: "Open-weight coding models on Apple Silicon search the ARM64
  sort/hash frontier. Powered by the MacProvider network."
- Live leaderboard link (will go live in Phase 7)
- 1-paragraph "What this is" with AlphaDev context
- "How to participate" → two paths:
  - **As a Mac owner**: link to MacProvider provider onboarding
  - **As a contestant**: not yet open in v0.1, link to issue tracker for
    interest
- Architecture sketch
- License (MIT)

### Phase 2: Module interface implementation

`harness/module.py` — abstract base class matching §2. Concrete subclass for
`problems/sort3-arm64/` in Phase 3.

### Phase 3: `sort3-arm64` module

`problems/sort3-arm64/`:
- `module.toml`
- `reference.s` — canonical 18-instruction ARM64 sort3 (generate via
  `clang -O3 -S` on a naive C sort3, hand-clean to stable form, commit)
- `tests.json` — ≥1000 fixed input triples and their sorted outputs
- `module.py` — implements `baseline / load / verify / score`

### Phase 4: Search harness

`harness/`:
- `loop.py` — main orchestration (read DB → call inference → verify →
  score → record receipt → repeat)
- `inference.py` — HTTP client for the MacProvider OpenAI-compatible
  endpoint, pinned headers, retry policy
- `prompts.py` — prompt templates. v0.1 strategy: "Here is the current
  best ARM64 routine for sort3 (N instructions). Propose a variant with
  N-1 instructions that still produces sorted output. Output ONLY the
  assembly, no commentary." Plus 2–3 ablation variants for A/B'ing.
- `store.py` — SQLite for candidates, scores, receipts, attempts
- `attest.py` — ed25519 keygen on first run, sign-per-candidate

Language: Python 3.11+. Standard libs only where possible; permitted deps:
`httpx`, `cryptography`, `keystone-engine` (assembler), `pytest`. NO MLX
in the harness — inference is over HTTP to MacProvider.

### Phase 5: Sandbox

`sandbox/`:
- `profile.sb` — macOS `sandbox-exec` profile, deny-by-default
- `runner.py` — assembles candidate with `keystone-engine` or `as`,
  executes in sandboxed subprocess with timeout, compares output to
  expected
- `tests/` — pytest cases that confirm the sandbox blocks: filesystem
  access, network, fork, exec, unauthorised syscalls

### Phase 6: Receipts

- ed25519 keypair generated once, private key in `data/sign.key` (gitignored),
  public key checked in at `receipts/PUBKEY`
- One JSON receipt per verified candidate at `receipts/<short_hash>.json`
- Verification script `bin/verify-receipt.py <receipt.json>` that anyone
  can run to confirm signature

### Phase 7: Public leaderboard

`web/` — minimal Next.js or static HTML+JS site:
- Single page: current best, attempt count, "powered by air5 +
  Qwen2.5-Coder-7B" attribution, last update timestamp, recent
  promotions feed
- Reads from a JSON endpoint that the harness updates (write a static
  JSON file every N attempts, commit + push, Vercel rebuilds — KISS for
  v0.1, no live API)
- Deploy to Vercel under a subdomain of `streamvc.live` (suggest
  `arm64golf.streamvc.live`, but defer DNS setup to the operator and
  document the steps in `OPERATOR_NOTES.md`)

### Phase 8: Air5 operator handoff

`AIR5_OPERATOR_NOTE.md` — instructions for the operator of node air5
(M4 MacBook Air, 16 GB) to enable arm64golf:

- Download `mlx-community/Qwen2.5-Coder-7B-Instruct-4bit` (~4.5 GB)
- Update phase3-binary config to serve this model **in addition to** (not
  instead of) the current `Qwen2.5-7B-Instruct-4bit` — verify phase3-binary
  supports multi-model; if not, document the constraint and ask the
  operator to choose
- Reconnect to coordinator, confirm via
  `https://coordinator.streamvc.live/v1/models` that the new model
  appears
- Expected resource usage during arm64golf load: ~5 GB resident,
  intermittent GPU bursts (each request is short)
- Kill switch: how the operator pauses arm64golf inference traffic
  without disconnecting from the network

## Success criteria (explicit)

The PoC reports back one of four outcomes. The thresholds are non-negotiable
— don't soften them in the writeup.

- **PASS-A (translation works).** Within 200 inference calls, the harness
  produces ≥1 syntactically valid ARM64 assembly candidate that passes the
  sandboxed verifier on all 1000+ test inputs. This proves
  Qwen2.5-Coder-7B can generate correct ARM64 at all.
- **PASS-B (rediscovery).** Within 10,000 inference calls (≈ 24 hours of
  air5 inference at typical throughput), the harness finds a 17-instruction
  ARM64 sort3 that passes verification. This matches AlphaDev's x86 record
  on ARM64 — a publishable result.
- **PASS-C (frontier signal).** Beyond PASS-B, ≥1 candidate at 16
  instructions either verifies (extraordinary — IMO-grade result for
  v0.1) OR the population of near-best candidates shows non-trivial
  structural diversity (suggests the search is exploring, not stuck).
- **FAIL.** None of the above within 10,000 calls. Document the failure
  modes (model produces invalid assembly, model only proposes trivial
  permutations, sandbox blocks more than expected, etc.) in
  `REPORT.md`. This is still a useful answer: it tells us 7B-class
  open-weight coders cannot do this task and we need to revisit scope.

`REPORT.md` is written at the end of the run regardless of outcome.

## Deliverables checklist

- [ ] `Augustas11/arm64golf` public GitHub repo exists, MIT licensed
- [ ] `SPEC.md` committed, covers §1–§10
- [ ] `README.md` reads as a recruiting page, links to MacProvider provider
      onboarding
- [ ] `problems/sort3-arm64/` module complete with reference, tests,
      verifier
- [ ] `harness/` runs end-to-end: inference → verify → score → receipt
- [ ] `sandbox/` blocks the documented escape vectors (pytest passes)
- [ ] `receipts/` contains ed25519 pubkey, at least one signed receipt
- [ ] `web/` leaderboard deployed to a public URL (Vercel)
- [ ] `AIR5_OPERATOR_NOTE.md` instructions tested by walking the air5
      operator through them (or marked as untested-pending-handoff)
- [ ] `REPORT.md` with the PASS-A/B/C or FAIL outcome and the data
      backing the verdict

## Out of scope for v0.1

- Multi-problem leaderboard. v0.1 is `sort3-arm64` only. Adding
  `sort4-arm64`, `sort5-arm64`, hash kernels is v0.2+.
- Multi-provider attestation. v0.1 trusts the single operator-run harness.
  k-of-n receipt agreement across providers is v0.2+.
- Contestant submissions. v0.1's only contestant is the harness itself.
  Public submission intake is v0.2+.
- Fine-tuning. v0.1 uses Qwen2.5-Coder-7B-Instruct-4bit as-is.
- Evolution / FunSearch-style program synthesis. v0.1 is direct mutation
  with population size 1.
- Comparison against frontier closed models. v0.1 is open-weight only by
  design.

## Order of operations

Phase 0 → Phase 1 (spec + README must be reviewed before code) → Phase 3 (one
real module before the harness wraps it) → Phase 2 (interface generalises
from the concrete) → Phase 5 (sandbox before any candidate runs) → Phase 4
(harness pulls it all together) → Phase 6 → Phase 7 → Phase 8. Commit at
each phase boundary. Push to `origin/main` (small project, no PR workflow
needed for v0.1).

=== END PROMPT ===
```

## What I do after handing this off

1. Review the spec doc (Phase 1) before approving code work.
2. Walk the air5 operator through the Phase 8 handoff in parallel with
   Phase 5 sandbox work.
3. Defer DNS for `arm64golf.streamvc.live` until Phase 7 is ready to deploy.
4. After the PoC reports PASS or FAIL, decide v0.2 scope based on what
   actually worked.
