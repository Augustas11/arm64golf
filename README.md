# arm64golf

**Open-weight coding models on Apple Silicon search the ARM64 sort/hash frontier. Powered by the MacProvider network.**

Live leaderboard: private test preview pending. Public launch is intentionally
deferred until the operator approves opening `arm64golf` to everyone.

## What This Is

`arm64golf` is an eventual public research leaderboard, currently in private test, where open-weight coding models served by MacProvider try to discover shorter ARM64 assembly routines than published references. The v0.1 proof of concept starts with one problem, `sort3-arm64`: sort three signed 64-bit integers in registers. It is inspired by Google DeepMind's AlphaDev work, which discovered shorter x86 sorting routines and reports `Sort3AlphaDev` at 17 instructions. This project is deliberately narrower: it asks whether an open-weight 7B coder model running on Apple Silicon can generate correct ARM64 mutations, rediscover a 17-instruction ARM64 `sort3`, and expose useful frontier signal toward 16 instructions.

## How To Participate

**As a Mac owner:** join MacProvider and turn an Apple Silicon Mac into an MLX inference provider. Start at the MacProvider provider onboarding flow: <https://github.com/Augustas11/macprovider#for-providers>.

**As a contestant:** public submissions are not open in v0.1. The only contestant is the harness itself, pinned to `air5` and `mlx-community/Qwen2.5-Coder-7B-Instruct-4bit`. Open an issue at <https://github.com/Augustas11/arm64golf/issues> to register interest in future contestant intake after launch.

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
static leaderboard JSON -> private preview now, public web page after launch approval
```

The harness pins inference to `https://api.streamvc.live/v1/chat/completions` with `X-MacProvider-Provider: air5`. Candidates are assembled into native ARM64 verifier binaries and run locally under a deny-by-default macOS `sandbox-exec` profile; `air5` only serves inference. Verified candidates receive ed25519 receipts binding problem, candidate hash, score, model, provider, harness version, and timestamp.

## Status

v0.1 is a bootstrap PoC. The success thresholds are:

- PASS-A: one syntactically valid ARM64 candidate verifies on 1000+ tests within 200 evaluated candidate responses.
- PASS-B: a 17-instruction verified ARM64 `sort3` appears within 10,000 evaluated candidate responses.
- PASS-C: a 16-instruction verified candidate appears, or near-best candidates show non-trivial structural diversity after PASS-B.
- FAIL: none of the above within 10,000 evaluated candidate responses, with failure modes documented in `REPORT.md`.

## License

MIT
