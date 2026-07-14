"""Vault discovery and indexing.

A *vault* is any directory tree of plain files — an Obsidian vault, a Zettel
folder, a docs/ tree. linkmend never requires an app-specific config; the
index is rebuilt from the filesystem on every run so it can never go stale.

Paths inside the vault are always handled as **vault-relative POSIX strings**
(``notes/api.md``), which keeps the planner, the journal, and every test
platform-independent. Hidden directories and files (leading dot) are ignored,
which conveniently excludes ``.git``, ``.obsidian``, and linkmend's own
``.linkmend`` journal directory.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Tuple

from .errors import VaultError

#: Extensions treated as Markdown notes (parsed for links).
MD_EXTENSIONS: Tuple[str, ...] = (".md", ".markdown")


def is_markdown(rel_path: str) -> bool:
    """True when ``rel_path`` names a Markdown note by extension."""
    return rel_path.lower().endswith(MD_EXTENSIONS)


def strip_md_extension(rel_path: str) -> str:
    """Drop a trailing Markdown extension, if present (case-insensitive)."""
    lower = rel_path.lower()
    for ext in MD_EXTENSIONS:
        if lower.endswith(ext):
            return rel_path[: -len(ext)]
    return rel_path


@dataclass(frozen=True)
class VaultIndex:
    """Immutable snapshot of every file and directory in a vault."""

    root: Path
    files: Tuple[str, ...]  # every regular file, sorted, vault-relative POSIX
    dirs: FrozenSet[str]  # every directory (not the root itself)
    md_files: Tuple[str, ...]  # subset of ``files`` that are Markdown notes
    _file_set: FrozenSet[str] = field(default=frozenset(), repr=False)

    def has_file(self, rel_path: str) -> bool:
        return rel_path in self._file_set

    def has_dir(self, rel_path: str) -> bool:
        return rel_path in self.dirs


def build_index(root: Path) -> VaultIndex:
    """Walk ``root`` and build a :class:`VaultIndex`.

    Deterministic: directories and files are visited in sorted order, and
    hidden entries (leading ``.``) are pruned so the journal never indexes
    itself.
    """
    root = Path(root)
    if not root.is_dir():
        raise VaultError(f"vault root is not a directory: {root}")
    files: List[str] = []
    dirs: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if rel_dir != ".":
            dirs.append(rel_dir)
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            files.append(rel)
    files.sort()
    md_files = tuple(f for f in files if is_markdown(f))
    return VaultIndex(
        root=root,
        files=tuple(files),
        dirs=frozenset(dirs),
        md_files=md_files,
        _file_set=frozenset(files),
    )


def normalize_rel(root: Path, raw: str) -> str:
    """Normalize a user-supplied path into a vault-relative POSIX string.

    Accepts absolute paths (must live inside the vault) and vault-relative
    ones; rejects anything that escapes the root. Trailing-slash intent is
    the caller's business — this only normalizes.
    """
    cleaned = raw.replace(os.sep, "/").rstrip("/") or "/"
    if os.path.isabs(cleaned) or (os.name == "nt" and os.path.isabs(raw)):
        try:
            cleaned = Path(raw).resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            raise VaultError(f"path is outside the vault: {raw}") from None
    rel = posixpath.normpath(cleaned)
    if rel in (".", "/"):
        raise VaultError("path may not be the vault root itself")
    if rel.startswith("../") or rel == "..":
        raise VaultError(f"path escapes the vault: {raw}")
    return rel


# ---------------------------------------------------------------------------
# File I/O helpers — byte-exact round-trips even for non-UTF-8 notes.
# ---------------------------------------------------------------------------


def read_note(root: Path, rel_path: str) -> Tuple[str, bytes]:
    """Return ``(text, raw_bytes)`` for a note.

    Decoding uses ``surrogateescape`` so a stray non-UTF-8 byte survives the
    edit → encode round-trip unchanged instead of crashing the whole run.
    """
    data = (Path(root) / rel_path).read_bytes()
    return data.decode("utf-8", errors="surrogateescape"), data


def encode_note(text: str) -> bytes:
    """Inverse of :func:`read_note`'s decoding."""
    return text.encode("utf-8", errors="surrogateescape")


def write_note(root: Path, rel_path: str, data: bytes) -> None:
    """Atomically write ``data`` (temp file + ``os.replace`` in-directory)."""
    target = Path(root) / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f".{target.name}.linkmend-tmp"
    tmp.write_bytes(data)
    os.replace(tmp, target)


def sha256_bytes(data: bytes) -> str:
    """Hex SHA-256 of raw bytes — the journal's integrity fingerprint."""
    return hashlib.sha256(data).hexdigest()


def stems_after_move(index: VaultIndex, mapping: Dict[str, str]) -> Dict[str, int]:
    """Count lowercase note stems as they will exist *after* a move.

    Used to decide whether a bare wiki link name (``[[Note]]``) stays
    unambiguous post-move or must be widened to a vault-relative path.
    """
    counts: Dict[str, int] = {}
    for f in index.files:
        new = mapping.get(f, f)
        if is_markdown(new):
            key = posixpath.basename(strip_md_extension(new)).lower()
        else:
            key = posixpath.basename(new).lower()
        counts[key] = counts.get(key, 0) + 1
    return counts
