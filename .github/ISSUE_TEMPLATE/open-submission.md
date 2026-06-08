---
name: Open submission
about: Submit ARM64 assembly for operator verification and publication.
title: "open-submission: <one-line summary>"
labels: ['open-submission']
---

## Assembly source

Paste the complete ARM64 assembly source here. The operator will save this block locally before verification.

```asm

```

## Score claim

Declared instruction count after normalization:

## Declared producer

- model_id:
- provider/runtime:
- search strategy:

## Submitter handle

@your-github-username

The operator will populate `attestation.details.issue_url` with this issue's URL.

## Local verification confirmation

I have run the assembly locally and it produces the expected sorted outputs on the standard 1200 cases (or confirmed via my own verifier).

## Acknowledgement

I understand the operator signs the receipt; my attribution is in this issue link only. All attestation.details string fields (declared_model_id, declared_provider, declared_search_strategy, submitter_handle, issue_url) are sanitized by the operator workflow before signing — control characters stripped, lengths capped per SPEC §11.1.
