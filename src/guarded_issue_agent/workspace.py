"""Filesystem sandbox used by the trusted controller."""

from __future__ import annotations

import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from guarded_issue_agent.errors import ApplyError, PolicyViolation, StalePlanError
from guarded_issue_agent.policy import WorkspacePolicy
from guarded_issue_agent.utils import read_limited, sha256_bytes


def path_is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=True))
    except (FileNotFoundError, ValueError):
        return False
    return True


@dataclass(frozen=True)
class TextFile:
    path: str
    content: str
    sha256: str


class ReadOnlyWorkspace:
    """Narrow model-facing view with no write operation."""

    __slots__ = ("__workspace",)

    def __init__(self, workspace: "Workspace") -> None:
        self.__workspace = workspace

    def read_text(self, raw_path: str) -> TextFile:
        return self.__workspace.read_text(raw_path)


class Workspace:
    """Reads and replaces regular UTF-8 files under a fixed repository root."""

    def __init__(self, root: Path, policy: WorkspacePolicy) -> None:
        requested = root.expanduser()
        if requested.is_symlink():
            raise PolicyViolation(f"workspace root must not be a symlink: {requested}")
        try:
            resolved = requested.resolve(strict=True)
        except FileNotFoundError as exc:
            raise PolicyViolation(f"workspace does not exist: {requested}") from exc
        if not resolved.is_dir():
            raise PolicyViolation(f"workspace must be a directory: {resolved}")
        self.root = resolved
        self.policy = policy

    def ensure_external_artifact_path(self, path: Path) -> Path:
        resolved = path.expanduser().resolve(strict=False)
        if path_is_within(resolved, self.root):
            raise PolicyViolation("run artifacts must be stored outside the workspace")
        return resolved

    def _resolve_regular_file(self, raw_path: str) -> tuple[str, Path]:
        normalized = self.policy.validate_relative_path(raw_path)
        relative = PurePosixPath(normalized)
        current = self.root
        for part in relative.parts:
            current = current / part
            try:
                metadata = current.lstat()
            except FileNotFoundError as exc:
                raise PolicyViolation(f"planned file does not exist: {normalized}") from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise PolicyViolation(f"symlinks are prohibited in planned paths: {normalized}")
        try:
            resolved = current.resolve(strict=True)
            resolved.relative_to(self.root)
        except (FileNotFoundError, ValueError) as exc:
            raise PolicyViolation(f"path escapes the workspace: {normalized}") from exc
        if not resolved.is_file():
            raise PolicyViolation(f"planned path is not a regular file: {normalized}")
        return normalized, resolved

    def read_text(self, raw_path: str) -> TextFile:
        normalized, resolved = self._resolve_regular_file(raw_path)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(resolved, flags)
        except OSError as exc:
            raise PolicyViolation(f"unable to open planned file {normalized}: {exc}") from exc
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise PolicyViolation(f"planned path is not a regular file: {normalized}")
            payload = read_limited(descriptor, self.policy.max_file_bytes)
        finally:
            os.close(descriptor)
        if len(payload) > self.policy.max_file_bytes:
            raise PolicyViolation(f"planned file exceeds byte limit: {normalized}")
        try:
            content = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PolicyViolation(f"planned file is not UTF-8 text: {normalized}") from exc
        return TextFile(path=normalized, content=content, sha256=sha256_bytes(payload))

    def replace_existing(self, raw_path: str, *, expected_sha256: str, content: str) -> str:
        current = self.read_text(raw_path)
        if current.sha256 != expected_sha256:
            raise StalePlanError(
                f"file changed after planning: {current.path}; expected {expected_sha256}, "
                f"found {current.sha256}"
            )
        payload = content.encode("utf-8")
        if len(payload) > self.policy.max_file_bytes:
            raise PolicyViolation(f"replacement file exceeds byte limit: {current.path}")

        _, target = self._resolve_regular_file(current.path)
        mode = stat.S_IMODE(target.stat().st_mode)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".guarded-agent-", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, mode)
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written == 0:
                    raise OSError("zero-byte write while replacing workspace file")
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1

            # Re-check immediately before replacement. This detects ordinary stale
            # work but is not an atomic compare-and-swap against another local writer.
            # os.replace replaces a link itself rather than following it if the target
            # changed concurrently.
            latest = self.read_text(current.path)
            if latest.sha256 != expected_sha256:
                raise StalePlanError(f"file changed while applying: {current.path}")
            os.replace(temporary, target)
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return sha256_bytes(payload)


def rollback_changes(
    workspace: Workspace,
    applied: list[tuple[str, str, str]],
) -> None:
    failures: list[str] = []
    for path, original_content, applied_sha256 in reversed(applied):
        try:
            workspace.replace_existing(
                path,
                expected_sha256=applied_sha256,
                content=original_content,
            )
        except Exception as exc:  # pragma: no cover - exceptional recovery path
            failures.append(f"{path}: {exc}")
    if failures:
        raise ApplyError(
            "apply failed and rollback was incomplete; inspect the workspace: "
            + "; ".join(failures)
        )
