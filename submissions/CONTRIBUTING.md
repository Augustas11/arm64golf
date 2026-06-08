# Open Submission Contributions

The open-submission track lets contestants submit raw ARM64 assembly for `sort3-arm64`. You write the assembly, file a GitHub issue, and the operator verifies it locally. If it passes, the operator signs an `open-submission` receipt, publishes it into SQLite, exports `web/public/leaderboard.json`, then commits and pushes the updated public record.

## Honesty Contract

The signed receipt proves two things: the submitted assembly verified against the standard cases, and the attestation JSON was claimed when the operator signed it. It does not prove the contestant identity, model, provider, runtime, or search story is true. Contestant attribution lives in the GitHub issue link and the sanitized `attestation.details.submitter_handle` field only.

## Required Attestation Fields

- `declared_model_id`: the model or system you claim produced or helped produce the candidate.
- `declared_provider`: the provider, runtime, host, or local environment you claim was used.
- `declared_search_strategy`: short prose describing the search method, prompt loop, manual edits, or copied source.
- `submitter_handle`: your GitHub handle, for example `@your-github-username`.
- `issue_url`: the GitHub issue URL; the operator fills this from the submitted issue.

## Submission Checklist

1. Write a complete ARM64 assembly routine for `sort3-arm64`.
2. Verify it locally against the standard 1200 cases, or with your own verifier.
3. Open an issue with the `open-submission` template.
4. Paste the assembly source into the fenced code block.
5. Fill in the score claim, producer fields, search strategy, and submitter handle.
6. Confirm the local verification and acknowledgement text.
7. Wait for the operator to save the assembly, build the attestation JSON, run `bin/verify-candidate.py`, and publish with `bin/publish-open-submission.py`.

## Worked Example

Use [example.s](example.s) and [example.attestation.json](example.attestation.json) as the concrete shape. The baseline example demonstrates the end-to-end plumbing. The actual seed candidate already has a reference-baseline receipt and cannot be relabeled as open-submission, so re-running publish against the seed assembly will be REFUSED with a clear attribution error. To exercise a fresh publish, modify the assembly slightly (rename a register, reorder a non-load-bearing line) so the candidate_hash differs. Copy these files only as a format example, then replace the assembly and every placeholder value with your real submission details.

## After Submission

The operator review is best-effort and has no SLA. The operator may reject a submission that fails verification, has an attestation that does not validate, or whose saved assembly does not match the signed receipt's `candidate_hash`.

When a submission publishes, the leaderboard row shows `model_id` and `provider_id` as `open-submission`. Open submissions are intentionally excluded from `pairs[]`; they appear as individual leaderboard rows instead of synthetic provider/model/template aggregates.

## Reading The Receipt

Open `receipts/<candidate_hash_short>.json`. The `payload.candidate_hash` is the SHA-256 of normalized assembly source, `payload.score` is the normalized instruction count, and `payload.attestation.kind` is `open-submission`. The `payload.attestation.details` object contains the five contestant-provided fields. The `signature` binds that payload to the operator public key in `receipts/PUBKEY`.
