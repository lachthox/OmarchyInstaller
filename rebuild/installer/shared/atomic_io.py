"""Crash-resistant writes for installer state and metadata."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: str | Path, content: bytes, *, mode: int = 0o600) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        temp_path = Path(temp_name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, destination)
        _fsync_directory(destination.parent)
        return destination
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def atomic_write_text(
    path: str | Path,
    content: str,
    *,
    encoding: str = "utf-8",
    mode: int = 0o600,
) -> Path:
    return atomic_write_bytes(path, content.encode(encoding), mode=mode)


def atomic_write_json(path: str | Path, payload: Any, *, mode: int = 0o600) -> Path:
    serialized = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    return atomic_write_text(path, serialized, mode=mode)
