# arm64golf

Open as of 2026-06-08. The challenge is live — submit, contribute, or host a Mac.

## Current surface

12 instructions — current shortest verified ARM64 sort3.

- 17 — AlphaDev x86 reference (Nature 618, 2023)
- 18 — clang -O3 ARM64 baseline
- 12 — arm64golf current best

This is a committed snapshot; the current best may have improved since this README was committed, so see the live leaderboard for the latest score.

arm64golf is a public, signed leaderboard accumulating shortest-known ARM64 routines — not claiming authority, building it.

## Best verified per provider/model/template

The web page renders `web/public/leaderboard.json` as the primary chart: Best verified per (provider, model, template). Lower instruction counts are better, and entries with no verified candidate render as `none`.

## Trajectory

The page also renders Best-known instruction count over time from verified `rows[]`, sorted by `discovered_at`. The running minimum shows the move from the 18-instruction baseline to the current 12-instruction best.

## Score history

The score history table lists every verified `sort3-arm64` candidate with score, candidate hash, model, provider, receipt signature prefix, and discovery time. Replay any claim with `bin/verify-receipt.py`.

## How it works

Submitted ARM64 assembly is assembled, sandboxed under `sandbox-exec`, and run against 1200 deterministic test cases. Any failure rejects the candidate. Passing candidates are hashed, scored by instruction count, and signed into an ed25519 receipt anyone can replay.

## Will you find a shorter routine?

sort3, sort4, sort5, hash variants, small `memcmp`, popcount, leading-zero count — fundamental routines that execute trillions of times a day on every modern device. Compilers cannot find their shortest forms; their search space is too constrained. There is no public source today for what the shortest known ARM64 implementation of X is.

Every entry is replayable with the public key via `bin/verify-receipt.py`. The leaderboard does not claim 12 is globally shortest — it accumulates the shortest verified to date. Have you seen shorter? Submit it.

## Participate

### Host a Mac

Apple Silicon Macs with idle hours become research infrastructure. Your provider id is signed into every receipt produced on your node.

→ [Run a provider on MacProvider](https://github.com/Augustas11/macprovider#for-providers)

### Write a routine

Submit ARM64 assembly that beats the current best on the leaderboard. The verifier signs passing candidates into the public log.

→ [Submit a routine](https://github.com/Augustas11/arm64golf/issues/new?template=open-submission.md)

### Contribute a prompt

Prompt templates are first-class artifacts. When a template finds structure, its id is signed into the resulting receipts.

→ [Contribute a prompt template](https://github.com/Augustas11/arm64golf/blob/main/prompts/CONTRIBUTING.md)

## What's next

- sort3 today at 12; can 11 be reached?
- sort4 (AlphaDev x86: 28). ARM64 unknown.
- sort5 (AlphaDev x86: 43). ARM64 unknown.
- fixed-size hash, small `memcmp`/`memcpy`/`strlen`, popcount, leading-zero count.

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
- [REPORT.md](REPORT.md) — current results
- [prompts/CONTRIBUTING.md](prompts/CONTRIBUTING.md) — prompt templates
- [submissions/CONTRIBUTING.md](submissions/CONTRIBUTING.md) — open submissions
- [bin/](bin/) — operator tools

## License

MIT
