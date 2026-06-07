from __future__ import annotations

import base64
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
except ModuleNotFoundError:  # pragma: no cover - exercised only without optional dep
    serialization = None
    Ed25519PrivateKey = None
    Ed25519PublicKey = None


@dataclass(frozen=True)
class Receipt:
    path: Path
    signature: str


def ensure_keypair(private_path: Path, public_path: Path) -> None:
    if Ed25519PrivateKey is None or serialization is None:
        raise RuntimeError("cryptography is required for ed25519 receipts")
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    if private_path.exists() and public_path.exists():
        return

    key = Ed25519PrivateKey.generate()
    private_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    private_path.write_bytes(private_bytes)
    private_path.chmod(0o600)
    public_path.write_text(base64.b64encode(public_bytes).decode("ascii") + "\n")


def sign_receipt(payload: dict[str, object], private_path: Path, public_path: Path, out_dir: Path) -> Receipt:
    ensure_keypair(private_path, public_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    short_hash = str(payload["candidate_hash"])[:12]
    path = out_dir / f"{short_hash}.json"
    if path.exists():
        try:
            verify_receipt(path)
            envelope = json.loads(path.read_text())
            if envelope.get("payload") == payload:
                return Receipt(path=path, signature=str(envelope["signature"]))
        except Exception:
            pass

    key = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
    canonical = canonical_json(payload)
    signature = key.sign(canonical)
    signature_b64 = base64.b64encode(signature).decode("ascii")
    envelope = {
        "payload": payload,
        "signature": signature_b64,
        "public_key": public_path.read_text().strip(),
    }
    atomic_write_text(path, json.dumps(envelope, indent=2, sort_keys=True) + "\n")
    return Receipt(path=path, signature=signature_b64)


def atomic_write_text(path: Path, content: str) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    replaced = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(content)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_path, path)
        replaced = True
        fsync_directory(path.parent)
    finally:
        if not replaced:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


def fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def verify_receipt(path: Path) -> bool:
    if Ed25519PublicKey is None:
        raise RuntimeError("cryptography is required for ed25519 receipts")
    envelope = json.loads(path.read_text())
    public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(envelope["public_key"]))
    public_key.verify(base64.b64decode(envelope["signature"]), canonical_json(envelope["payload"]))
    return True


def canonical_json(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
