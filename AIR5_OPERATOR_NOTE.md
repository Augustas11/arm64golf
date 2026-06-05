# air5 Operator Note

This note enables `arm64golf` traffic on provider node `air5`, the M4 MacBook
Air with 16 GB unified memory.

## Goal

Serve `mlx-community/Qwen2.5-Coder-7B-Instruct-4bit` through MacProvider so
the `arm64golf` harness can pin inference to:

```text
https://api.streamvc.live/v1/chat/completions
X-MacProvider-Provider: air5
model: mlx-community/Qwen2.5-Coder-7B-Instruct-4bit
```

## Download Model

Download or prewarm:

```text
mlx-community/Qwen2.5-Coder-7B-Instruct-4bit
```

Expected download size is roughly 4.5 GB. Expected resident memory during
arm64golf load is roughly 5 GB with short intermittent GPU bursts.

## Configure phase3-binary

Serve the coder model in addition to the current default model
`mlx-community/Qwen2.5-7B-Instruct-4bit` if phase3-binary supports multiple
models on the node.

If phase3-binary supports only one active model, document that constraint and
choose explicitly:

- keep general Qwen online and postpone arm64golf, or
- switch to Qwen2.5-Coder during an arm64golf run window.

Do not let arm64golf silently attribute non-coder Qwen responses to the coder
model.

## Reconnect And Verify

Reconnect the provider to the coordinator, then verify the model appears:

```bash
curl -fsS https://coordinator.streamvc.live/v1/models
bin/check-air5-model.py --provider-alias m4
```

If `https://coordinator.streamvc.live/v1/models` is unavailable or returns
404, check the authenticated public API model list instead:

```bash
MACPROVIDER_API_KEY=... bin/check-air5-model.py \
  --url https://api.streamvc.live/v1/models \
  --provider-alias m4
```

Confirm:

- provider id exposed to buyers is `air5`, or document the actual live id
- model list includes `mlx-community/Qwen2.5-Coder-7B-Instruct-4bit`
- provider remains healthy under short chat-completion requests

If the live provider id is still `m4`, either update the coordinator-facing id
to `air5` or document the `air5`/`m4` mapping before running receipts.

## Kill Switch

Preferred kill switch:

1. remove or pause only the coder model from the provider config
2. keep the node connected to MacProvider if possible
3. confirm `https://coordinator.streamvc.live/v1/models` no longer routes the
   coder model to `air5`

Emergency kill switch:

1. stop the local phase3-binary provider service
2. confirm the coordinator marks `air5` unavailable
3. note the stop time in `REPORT.md`

## Operator Checklist

- [ ] Coder model downloaded or prewarmed
- [ ] Multi-model support verified, or single-model constraint documented
- [ ] Provider reconnected
- [ ] Coordinator `/v1/models` includes the coder model
- [ ] `bin/check-air5-model.py --provider-alias m4` passes
- [ ] Public provider id confirmed as `air5` or mapping documented
- [ ] Kill switch tested or documented as untested-pending-handoff
