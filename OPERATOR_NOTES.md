# Operator Notes

## GitHub

Target test repo:

```text
https://github.com/Augustas11/arm64golf
```

The repo is private during the test phase. Do not make it public until the
operator explicitly approves launch.

```bash
git push -u origin main
```

Current state: `origin` points at the private repo
`https://github.com/Augustas11/arm64golf.git`.

## Static Leaderboard Deployment

The web surface is static and lives under `web/`.

During testing, deploy previews only. Do not attach
`arm64golf.streamvc.live` or publish a production deployment until the repo and
leaderboard are approved for public launch.

Local preview:

```bash
python3 -m http.server 8765 --directory web
```

Suggested Vercel settings:

- project root: `web`
- framework preset: Other
- build command: empty
- output directory: `.`
- config file: `web/vercel.json`

Future public hostname:

```text
arm64golf.streamvc.live
```

DNS setup is deferred until launch approval. Point the subdomain to the Vercel
target shown by `vercel domains` or the Vercel dashboard only after approval.

## Run Notes

Before starting a real search:

1. complete `AIR5_OPERATOR_NOTE.md`
2. confirm `MACPROVIDER_API_KEY` is set
3. run `bin/verify-receipt.py` against the seed receipt
4. run `bin/check-air5-model.py --provider-alias m4` until the coder model and
   intended provider id are visible; use `--url https://api.streamvc.live/v1/models`
   with `MACPROVIDER_API_KEY` if the coordinator endpoint is unavailable
5. run local preflight and sandbox tests on the operator machine
6. run the harness with a small round count before a 10,000-call run

Example:

```bash
bin/check-air5-model.py --provider-alias m4
bin/preflight.py --run-tests
.venv/bin/pytest sandbox/tests -q
.venv/bin/python sandbox/runner.py
.venv/bin/python harness/loop.py --rounds 1
```
