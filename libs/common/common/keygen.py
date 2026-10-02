"""service-keys one-shot: one Ed25519 identity per service.

  python -m common.keygen /keys gateway content search

Writes /keys/<name>/private.pem (only that service mounts this subpath) and /keys/public/<name>.pem
(every service mounts `public`). Idempotent: existing keys are kept, so restarts do not rotate identities.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SERVICE_UID = int(os.environ.get("SERVICE_UID", "10001"))   # the uid every service image runs as


def ensure_key(root: Path, name: str) -> bool:
    """Create the key pair for `name` if missing. Returns True if a new key was generated."""
    priv_dir, pub_dir = root / name, root / "public"
    priv_dir.mkdir(parents=True, exist_ok=True)
    pub_dir.mkdir(parents=True, exist_ok=True)
    priv_path, pub_path = priv_dir / "private.pem", pub_dir / f"{name}.pem"
    created = False
    if not priv_path.exists():
        key = Ed25519PrivateKey.generate()
        priv_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                serialization.NoEncryption()))
        created = True
    key = serialization.load_pem_private_key(priv_path.read_bytes(), password=None)
    pub_path.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                       serialization.PublicFormat.SubjectPublicKeyInfo))
    if os.geteuid() == 0:
        os.chown(priv_dir, SERVICE_UID, SERVICE_UID)
        os.chown(priv_path, SERVICE_UID, SERVICE_UID)
    priv_dir.chmod(0o500)
    priv_path.chmod(0o400)
    pub_path.chmod(0o444)
    return created


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write("usage: python -m common.keygen <keys dir> <service> [<service> ...]\n")
        return 2
    root = Path(argv[0])
    for name in argv[1:]:
        state = "generated" if ensure_key(root, name) else "kept"
        sys.stdout.write(f"service-keys: {name}: {state}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
