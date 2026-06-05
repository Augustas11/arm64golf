# Operator Notes

## GitHub

Target repo:

```text
https://github.com/Augustas11/arm64golf
```

This local environment currently cannot create or push the repo because both
configured `gh` tokens report invalid authentication. Re-authenticate the
`Augustas11` account, then run:

```bash
gh auth switch -u Augustas11
gh repo create Augustas11/arm64golf --public --source=. --remote=origin --description "Open-weight coding models on Apple Silicon search the ARM64 sort/hash frontier. Powered by MacProvider."
git push -u origin main
```

## Static Leaderboard Deployment

The web surface is static and lives under `web/`.

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

Suggested public hostname:

```text
arm64golf.streamvc.live
```

DNS setup is deferred until the Vercel project exists. Point the subdomain to
the Vercel target shown by `vercel domains` or the Vercel dashboard.

## Run Notes

Before starting a real search:

1. complete `AIR5_OPERATOR_NOTE.md`
2. confirm `MACPROVIDER_API_KEY` is set
3. run `bin/verify-receipt.py` against the seed receipt
4. run sandbox tests on the operator machine
5. run the harness with a small round count before a 10,000-call run

Example:

```bash
.venv/bin/pytest sandbox/tests -q
.venv/bin/python sandbox/runner.py
.venv/bin/python harness/loop.py --rounds 1
```
