# arm64golf

**Open-weight coding models on Apple Silicon search the ARM64 sort/hash frontier. Powered by the MacProvider network.**

Live leaderboard: pending Phase 7 deployment.

## What This Is

`arm64golf` is a public research leaderboard where open-weight coding models served by MacProvider try to discover shorter ARM64 assembly routines than published references. The v0.1 proof of concept starts with one problem, `sort3-arm64`: sort three signed 64-bit integers in registers. It is inspired by Google DeepMind's AlphaDev work, which discovered shorter x86 sorting routines and reports `Sort3AlphaDev` at 17 instructions. This project is deliberately narrower: it asks whether an open-weight 7B coder model running on Apple Silicon can generate correct ARM64 mutations, rediscover a 17-instruction ARM64 `sort3`, and expose useful frontier signal toward 16 instructions.

## How To Participate

**As a Mac owner:** join MacProvider and turn an Apple Silicon Mac into an MLX inference provider. Start at the MacProvider provider onboarding flow: <https://github.com/Augustas11/macprovider#for-providers>.

**As a contestant:** public submissions are not open in v0.1. The only contestant is the harness itself, pinned to `air5` and `mlx-community/Qwen2.5-Coder-7B-Instruct-4bit`. Open an issue to register interest in future contestant intake.

## Architecture

```text
Qwen2.5-Coder-7B on air5
        |
        | OpenAI-compatible chat completions
        v
search harness -> sandboxed sort3 verifier -> SQLite store
        |                    |
        |                    v
        |              ed25519 receipt
        v
static leaderboard JSON -> public web page
```

The harness pins inference to `https://api.streamvc.live/v1/chat/completions` with `X-MacProvider-Provider: air5`. Candidates run locally under a deny-by-default macOS sandbox; `air5` only serves inference. Verified candidates receive ed25519 receipts binding problem, candidate hash, score, model, provider, harness version, and timestamp.

## Status

v0.1 is a bootstrap PoC. The success thresholds are:

- PASS-A: one syntactically valid ARM64 candidate verifies on 1000+ tests within 200 inference calls.
- PASS-B: a 17-instruction verified ARM64 `sort3` appears within 10,000 inference calls.
- PASS-C: a 16-instruction verified candidate appears, or near-best candidates show non-trivial structural diversity after PASS-B.
- FAIL: none of the above within 10,000 calls, with failure modes documented in `REPORT.md`.

## License

MIT
