#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def canonical_json(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify(path: Path) -> bool:
    envelope = json.loads(path.read_text())
    public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(envelope["public_key"]))
    public_key.verify(base64.b64decode(envelope["signature"]), canonical_json(envelope["payload"]))
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    verify(args.receipt)
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
