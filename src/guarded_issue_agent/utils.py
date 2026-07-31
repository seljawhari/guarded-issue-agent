"""Small, dependency-free helpers used across the package."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from guarded_issue_agent.errors import InputValidationError

MAX_JSON_BYTES = 1_000_000


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def read_limited(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    remaining = limit + 1
    while remaining > 0:
        chunk = os.read(descriptor, min(65_536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise InputValidationError(f"{label} must be a JSON object with string keys")
    return value


def expect_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] | None = None,
    label: str,
) -> None:
    optional = optional or set()
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - required - optional)
    if missing:
        raise InputValidationError(f"{label} is missing fields: {', '.join(missing)}")
    if unknown:
        raise InputValidationError(f"{label} has unknown fields: {', '.join(unknown)}")


def require_string(
    value: Any,
    label: str,
    *,
    min_length: int = 1,
    max_length: int,
) -> str:
    if not isinstance(value, str):
        raise InputValidationError(f"{label} must be a string")
    if not min_length <= len(value) <= max_length:
        raise InputValidationError(
            f"{label} must contain between {min_length} and {max_length} characters"
        )
    if "\x00" in value:
        raise InputValidationError(f"{label} must not contain a NUL byte")
    return value


def require_string_list(
    value: Any,
    label: str,
    *,
    max_items: int,
    item_max_length: int,
) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > max_items:
        raise InputValidationError(f"{label} must be a list with at most {max_items} items")
    return tuple(
        require_string(item, f"{label}[{index}]", max_length=item_max_length)
        for index, item in enumerate(value)
    )


def load_json_file(path: Path, *, label: str) -> dict[str, Any]:
    source = path.expanduser()
    try:
        if source.is_symlink():
            raise InputValidationError(f"{label} must not be a symlink: {source}")
        resolved = source.resolve(strict=True)
        descriptor = os.open(resolved, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError as exc:
        raise InputValidationError(f"{label} does not exist: {source}") from exc
    except OSError as exc:
        raise InputValidationError(f"unable to open {label}: {source}: {exc}") from exc

    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise InputValidationError(f"{label} must be a regular file: {source}")
        payload = read_limited(descriptor, MAX_JSON_BYTES)
    finally:
        os.close(descriptor)

    if len(payload) > MAX_JSON_BYTES:
        raise InputValidationError(f"{label} exceeds the {MAX_JSON_BYTES}-byte limit")
    try:
        decoded = payload.decode("utf-8")
        parsed = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputValidationError(f"{label} must be valid UTF-8 JSON: {exc}") from exc
    return require_object(parsed, label)


def write_new_file(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    """Create a new artifact without following links or overwriting a prior run."""

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags, mode)
    except FileExistsError as exc:
        raise InputValidationError(f"refusing to overwrite existing artifact: {path}") from exc
    except OSError as exc:
        raise InputValidationError(f"unable to create artifact {path}: {exc}") from exc
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written == 0:
                raise OSError("zero-byte write while creating artifact")
            view = view[written:]
        os.fsync(descriptor)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
            descriptor = -1
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
