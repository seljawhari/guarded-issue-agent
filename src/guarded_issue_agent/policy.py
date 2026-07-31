"""Fail-closed path and change policy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from guarded_issue_agent.errors import PolicyViolation


@dataclass(frozen=True)
class WorkspacePolicy:
    """Limits what a model-authored plan may ask the controller to change."""

    allowed_roots: tuple[str, ...] = ("src", "tests", "docs")
    allowed_extensions: frozenset[str] = frozenset(
        {".py", ".md", ".txt", ".toml", ".json", ".yml", ".yaml"}
    )
    max_changes: int = 8
    max_file_bytes: int = 256_000
    max_find_bytes: int = 16_000
    max_replacement_bytes: int = 64_000

    def __post_init__(self) -> None:
        if not self.allowed_roots:
            raise PolicyViolation("at least one allowed root is required")
        for root in self.allowed_roots:
            if (
                not root
                or root in {".", ".."}
                or "/" in root
                or "\\" in root
                or root.startswith(".")
            ):
                raise PolicyViolation(f"invalid allowed root: {root!r}")

    def validate_relative_path(self, raw_path: str) -> str:
        if not raw_path or len(raw_path) > 300:
            raise PolicyViolation("path must contain 1 to 300 characters")
        if "\\" in raw_path:
            raise PolicyViolation("paths must use forward slashes")
        if any(ord(character) < 32 for character in raw_path) or ":" in raw_path:
            raise PolicyViolation("path contains a prohibited character")

        path = PurePosixPath(raw_path)
        if path.is_absolute() or raw_path.startswith("/"):
            raise PolicyViolation(f"absolute paths are prohibited: {raw_path}")
        if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            raise PolicyViolation(f"path traversal is prohibited: {raw_path}")
        if any(part.startswith(".") for part in path.parts):
            raise PolicyViolation(f"hidden paths are prohibited: {raw_path}")
        if path.parts[0] not in self.allowed_roots:
            allowed = ", ".join(self.allowed_roots)
            raise PolicyViolation(f"path must be under an allowed root ({allowed}): {raw_path}")
        if path.suffix.lower() not in self.allowed_extensions:
            raise PolicyViolation(f"file extension is not allowed: {raw_path}")
        return path.as_posix()

    def validate_change_size(self, find: str, replace: str) -> None:
        if not find:
            raise PolicyViolation("replace_once requires a non-empty find value")
        if find == replace:
            raise PolicyViolation("find and replacement values must differ")
        if len(find.encode("utf-8")) > self.max_find_bytes:
            raise PolicyViolation("find value exceeds the configured byte limit")
        if len(replace.encode("utf-8")) > self.max_replacement_bytes:
            raise PolicyViolation("replacement value exceeds the configured byte limit")
