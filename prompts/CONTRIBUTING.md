# Prompt Template Contributions

## What a Prompt Template Is

A prompt template is a string that becomes the user message sent to the model after the harness combines it with `MAIN_TEMPLATE`, any optional ablation block, and `.format()` values such as `instruction_count`, `target_count`, and `assembly` source.

For normal templates, `template_id` is the first 16 hex characters of `sha256(template body before .format())`. `chain_of_thought` is the current exception because it changes both system and user prompt content; its ID hashes `COT_SYSTEM_PROMPT` concatenated with the template body.

## Where Templates Live

Templates live in [harness/prompts.py](../harness/prompts.py) as `ABLATION_TEMPLATES`.

Current template names:

- `no_failed_context`
- `failed_context`
- `strict_no_memory`
- `structural_hint`
- `csel_hint`
- `dual_example`
- `pass_b_target`
- `chain_of_thought`

The `mock` path is an offline harness mode, not a prompt template in `ABLATION_TEMPLATES`.

## How to Propose a New Template

Open an issue with:

- the template body
- a one-line description of what you are trying to elicit
- a suggested `template_name`

Use the issue form here: <https://github.com/Augustas11/arm64golf/issues/new>.

The operator will compute `template_id`, validate that it does not collide with existing templates, run a small canary, and publish results.

## What the Operator Does With It

When a template lands, the operator registers it in `harness/prompts.py`, runs a bounded canary targeting roughly 200 candidate responses when provider quota permits against the default `air5` + `mlx-community/Qwen2.5-Coder-7B-Instruct-4bit` pair, and may also run it against other `(provider, model)` pairs. The exact evaluated count is published in `pairs[].evaluated_responses`.

The operator publishes the new `pairs[]` row and signs reference-harness receipts on verified candidates. Those receipts use `kind='reference-harness'` and sign `template_name` and `template_id` into `details`.

## What You Do Not Get

Contestants do not get their own signing key and do not get an attestation kind that names them. The receipt attests to `(provider, model, template)` only.

If you want your name attached, mention it in the issue. The contributor identity in the issue link is credit metadata, NOT cryptographic provenance. The receipt's `kind='reference-harness'` attestation does not name the contributor; it names the operator-run harness. The operator may credit you in the leaderboard row's future `discoverer-credit` field, which is a Phase 3+ TODO.

## References

- [SPEC.md Section 7](../SPEC.md#7-receipts)
- [bin/validate-receipts.py](../bin/validate-receipts.py) validates leaderboard rows and receipt signatures
- [harness/loop.py](../harness/loop.py) `validate_attestation()` validates attestation schema in process
- [tests/test_harness.py](../tests/test_harness.py) tests for `template_id` determinism
