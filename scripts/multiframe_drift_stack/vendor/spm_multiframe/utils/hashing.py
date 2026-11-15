from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 digest of *path* without loading the whole file in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dataset_id(items: list[tuple[str, str]]) -> str:
    """Create a deterministic dataset identifier from ``(relative_name, sha256)`` pairs."""
    digest = hashlib.sha256()
    for name, file_hash in sorted(items):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"
