# arm64golf

*arm64golf is an open, signed leaderboard for the shortest ARM64 routines.*

Live as of 2026-06-08. The challenge is live — host a Mac, write a routine, or contribute a prompt.

## Why this matters

The routines arm64golf targets — sort 3 integers, sort 4, sort 5, fixed-size hash, small `memcmp`, popcount, leading-zero count — execute trillions of times a day on the hardware that runs the modern world: iPhones, M-series Macs, modern Androids, every AWS Graviton instance. Compilers cannot find their shortest forms. Their search space is too constrained by correctness preservation through high-level passes. Manual superoptimization has found shorter forms since Massalin's 1987 paper, through STOKE (2013), through AlphaDev (Nature 618, 2023). But the published records are old, scoped to x86, or closed.

There is no public source today for the question "what is the shortest known ARM64 implementation of X?" A libc maintainer, a real-time-systems engineer, a compiler developer who wants to know the answer right now has nowhere to look. That gap is what arm64golf exists to close.

## What verified means here

A leaderboard is only as useful as its trust model. arm64golf's is explicit:

- Every entry passes a deterministic 1200-case verifier. Replay any claim with `bin/verify-receipt.py` — no trust in operators required. The cryptographic property is that nobody can fake a working routine; `score=12` means the routine actually sorts every test case correctly.
- Instruction counts are computed by a deterministic normalizer. Re-count any entry yourself via the same normalizer in `harness/store.py`.

When the leaderboard says current best is 12 instructions, it claims:

> 12 is the shortest ARM64 sort3 verified and signed into this public log to date.

It does not claim:

- 12 is globally optimal.
- 12 is the shortest known anywhere.

No public source for that broader claim exists; that gap is the point. The leaderboard's job is to accumulate the shortest known, with cryptographic provenance, from any source — papers, compiler intrinsics, hand-crafted routines, LLM searches, hybrid pipelines. Have you seen shorter? Submit it. The verifier runs, the receipt signs, the log appends — and you get the credit attached to that hash forever.

AlphaDev published x86 records in 2023 but no ARM64 numbers; their production artifacts are closed. arm64golf's contribution is not to compete with AlphaDev's authority — neither of us is a global oracle. Our contribution is the open public log itself: a place where the shortest known can converge.

## What we'll deliver

A growing reference set of shortest-known ARM64 implementations of fundamental routines, each one signed, each one reproducible:

- sort3 today at 12 instructions; can 11 be reached, or is 12 provably optimal?
- sort4 (AlphaDev x86 reference: 28). No published ARM64 number.
- sort5 (AlphaDev x86 reference: 43). No published ARM64 number.
- Fixed-size hash variants on common widths.
- Small `memcmp` / `memcpy` / `strlen` variants on common lengths.
- Bit-level primitives — popcount, leading-zero count.

Each entry gets an immutable hash a paper or libc patch can cite. Each routine compiler vendors and libc maintainers can evaluate directly, with a verified provenance trail. The order in which these problems get added depends on contributor interest and demand.

## How to join

### Host a Mac

If you have an Apple Silicon Mac with idle hours and at least 8 GB of unified memory, you become research infrastructure the moment you join. Your provider id is signed into every receipt your node produces, in the public log, forever.

→ [Run a provider on MacProvider](https://github.com/Augustas11/macprovider#for-providers)

### Write a routine

If you can write ARM64 assembly that sorts in fewer than 12 instructions, submit it. The operator runs the deterministic verifier and signs the result. Your hash on the public log forever; a future libc patch or paper can cite that exact hash.

Equally welcome: if you've seen a shorter ARM64 implementation in a paper, a compiler intrinsic, a codebase, a conference talk, or your own private notes — submit it. The receipt cares only that the routine verifies; it doesn't care where the routine came from. You get the credit attached to the hash.

→ [Submit a routine](https://github.com/Augustas11/arm64golf/issues/new?template=open-submission.md)  
→ [How submissions work](https://github.com/Augustas11/arm64golf/blob/main/submissions/CONTRIBUTING.md)

### Contribute a prompt

If you find a prompt that surfaces structure the existing templates miss, contribute it. The operator registers the template and signs the `template_id` into every receipt the template produces.

→ [Contribute a prompt template](https://github.com/Augustas11/arm64golf/blob/main/prompts/CONTRIBUTING.md)

## How verification works

Each submitted ARM64 routine is assembled into a native binary and executed under a deny-by-default macOS `sandbox-exec` profile against 1200 deterministic test cases. Any failure rejects the candidate. A passing candidate is hashed, scored by static instruction count after normalization, and bound into an ed25519 receipt. Anyone with `receipts/PUBKEY` can independently re-derive any score on the leaderboard from the recorded receipt and the candidate bytes.

## Run it yourself

```bash
git clone https://github.com/Augustas11/arm64golf.git
cd arm64golf
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

```bash
.venv/bin/pytest tests/test_harness.py -q
```

```bash
python3 -m http.server 8765 --directory web
# http://localhost:8765
```

```bash
cat web/public/leaderboard.json
```

```bash
.venv/bin/python bin/verify-receipt.py <receipt-path>
```

```bash
.venv/bin/python bin/validate-open-submission-flow.py --json
```

Running the marketplace harness in `harness/loop.py` requires `MACPROVIDER_API_KEY`. Explicit marketplace attribution for provider/model pairs is enabled with `--allow-marketplace-attribution`.

## Links

- [SPEC.md](SPEC.md) — full architecture
- [REPORT.md](REPORT.md) — current results and Phase 4 marketplace finding
- [prompts/CONTRIBUTING.md](prompts/CONTRIBUTING.md) — Track B, prompt templates
- [submissions/CONTRIBUTING.md](submissions/CONTRIBUTING.md) — Track C, open submissions
- [bin/](bin/) — operator tools

## License

MIT
