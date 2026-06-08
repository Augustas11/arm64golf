# arm64golf

*arm64golf is an open, signed leaderboard for the shortest ARM64 routines.*

Live as of 2026-06-08. The challenge is live — host a Mac, write a routine, or contribute a prompt.

## Why this matters

ARM64 powers iPhones, M-series Macs, modern Androids, AWS Graviton servers — an enormous fraction of all computation. Fundamental routines such as `sort3`, `sort4`, fixed-size hash, and small `memcmp` execute trillions of times a day; every instruction saved compounds.

AlphaDev (DeepMind, 2023) demonstrated learned search can find shorter implementations than the published references — for x86 only, with closed production artifacts. No equivalent public ARM64 result exists. arm64golf is the open answer: a public, verifiable, signed record of the shortest known ARM64 implementations, reproducible by anyone with the public key and the harness source.

## What we'll deliver

- A public, append-only log of shortest ARM64 implementations of fundamental routines, each bound to a deterministic verifier and an ed25519 signature
- A growing problem set — sort3 today; sort4, sort5, fixed-size hash, small memcmp on the same framework
- Citeable, immutable hashes that a paper or libc patch can reference
- Routines compiler vendors and libc maintainers can evaluate directly, with a verified provenance trail
- A trajectory toward the first open ARM64 equivalent of AlphaDev's published x86 results

Today the leaderboard is at sort3 with a current best of 12 instructions. AlphaDev never published an ARM64 sort3 number; the comparable x86 figure is 17. The clang -O3 ARM64 baseline is 18. Whether 11 (or lower) is reachable is genuinely open.

## How to join

### Host a Mac

If you have an Apple Silicon Mac with idle hours and at least 8 GB of unified memory, you become research infrastructure the moment you join. Your provider id is signed into every receipt your node produces, in the public log, forever.

→ [Run a provider on MacProvider](https://github.com/Augustas11/macprovider#for-providers)

### Write a routine

If you can write ARM64 assembly that sorts in fewer than 12 instructions, submit it. The operator runs the deterministic verifier and signs the result.

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
