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

`bin/preflight.py` verifies that `origin` is this repo and that GitHub reports
`PRIVATE`. Do not use `--allow-public-launch` unless the operator has explicitly
approved making arm64golf public.

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
3. run `bin/validate-air5-handoff.py --json` to confirm the air5 note and
   no-touch owner coordination rules are intact
4. run `bin/verify-receipt.py` against the seed receipt
5. run `bin/validate-docs.py --json` to confirm `SPEC.md` and `README.md`
   still match the required private-test/recruiting contracts
6. run `bin/audit-deliverables.py --json` to confirm local artifacts are
   complete and only approved pending/deferred gates remain
7. run `bin/validate-harness-smoke.py --json` to confirm mock inference,
   sandbox verification, scoring, receipt signing, SQLite persistence, and
   leaderboard export work end to end
8. run `bin/validate-inference-config.py --json` to confirm the request stays
   pinned to the MacProvider endpoint, coder model, `air5` provider header,
   v0.1 sampling defaults, and authentication failure behavior
9. run `bin/validate-sandbox.py --json` to confirm the sandbox profile,
   native runner, escape-vector blocks, timeout, and memory-cap reporting
10. run `bin/validate-receipts.py --json` to confirm every leaderboard row is
   backed by a matching signed receipt
11. run `bin/validate-report.py --json` to confirm `REPORT.md` is generated
    from tracked leaderboard evidence and still names the pending live-run gates
12. run `bin/validate-web.py --json` to confirm the static leaderboard files
   match the JSON contract before preview/deploy
13. run `bin/ready-live-run.py --run-tests --json` as the aggregate readiness
   gate; it should report no blockers before a live search
14. run `bin/check-air5-model.py --provider-alias m4` until the coder model and
   intended provider id are visible; use `--url https://api.streamvc.live/v1/models`
   with `MACPROVIDER_API_KEY` if the coordinator endpoint is unavailable
15. run local preflight and sandbox tests on the operator machine
16. run the harness with a small round count before a 10,000-call run

Example:

```bash
bin/validate-docs.py --json
bin/validate-air5-handoff.py --json
bin/audit-deliverables.py --json
bin/validate-harness-smoke.py --json
bin/validate-inference-config.py --json
bin/validate-sandbox.py --json
bin/validate-receipts.py --json
bin/validate-report.py --json
bin/validate-web.py --json
bin/ready-live-run.py --run-tests --json
bin/check-air5-model.py --provider-alias m4
bin/preflight.py --run-tests
.venv/bin/pytest sandbox/tests -q
.venv/bin/python sandbox/runner.py
.venv/bin/python harness/loop.py --rounds 1 --mock-response-file problems/sort3-arm64/reference.s
.venv/bin/python bin/summarize-run.py --db data/arm64golf.sqlite
.venv/bin/python bin/write-report.py --db data/arm64golf.sqlite
.venv/bin/python harness/loop.py --rounds 1 --max-candidate-responses 8
.venv/bin/python harness/loop.py --rounds 1250 --max-candidate-responses 10000
```

If the local command sandbox cannot let `bin/audit-deliverables.py` call the
GitHub API, use `bin/audit-deliverables.py --offline --json` for the local
artifact audit and run `bin/preflight.py --run-tests` or `gh repo view
Augustas11/arm64golf --json visibility` separately to prove the repo is still
private.

If the local command sandbox cannot apply macOS `sandbox-exec` profiles, run
`bin/validate-harness-smoke.py --json`, `bin/validate-sandbox.py --json`,
`sandbox/runner.py`, and `bin/audit-deliverables.py --json` from the operator
shell. These gates are supposed to prove the real sandbox path, not a
Python-only fallback.

`bin/ready-live-run.py` is the aggregate gate, but it is intentionally
conservative: it reports blockers until `MACPROVIDER_API_KEY`, GitHub private
visibility, preflight, and the air5 model check all pass in the same operator
environment. If a command sandbox blocks nested GitHub API calls, run the
individual checks above from the operator shell and keep the readiness output
as evidence of the remaining external blockers.

Do not attempt air5 software upgrades, model installs, or phase3-binary
configuration changes from this repo workflow. If `bin/check-air5-model.py`
or `bin/ready-live-run.py` shows that air5 needs a model download, provider
software upgrade, config edit, reconnect, or kill-switch change, hand that
specific action to Augustas so it can be coordinated with the air5 owner.

The `--mock-response-file` command is the offline end-to-end smoke. It records
one synthetic attempt and exercises candidate loading, native sandbox
verification, scoring, receipt signing, SQLite persistence, and static JSON
export without calling MacProvider.

Use `bin/summarize-run.py` after smoke, live test, and long runs to derive the
current PENDING/RUNNING/PASS/FAIL status from the SQLite attempt/evaluation
ledger instead of hand-counting responses.
Use `bin/write-report.py` to regenerate `REPORT.md` from the same evidence.

The harness caps live runs with `--max-candidate-responses`; use `10000` for
the v0.1 PASS-B/FAIL run. The default stop condition continues after PASS-A
and stops on PASS-B, PASS-C, or FAIL.
