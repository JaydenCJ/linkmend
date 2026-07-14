"""Execute a :class:`~linkmend.plan.MovePlan` on disk.

Ordering matters and is fixed:

1. **read** every to-be-edited note and compute its new content (with a
   defensive check that each span still contains exactly the text the
   planner saw — if a file changed between plan and apply, we stop before
   touching anything);
2. **move** files (parents created, empty source directories pruned);
3. **write** the edited content at each note's *post-move* location, via a
   temp file and ``os.replace`` so a crash never leaves a half-written note.

The returned :class:`ApplyResult` carries the byte-exact before/after images
that the journal needs to make the whole transaction undoable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from .errors import PlanError
from .plan import LinkEdit, MovePlan
from .vault import encode_note, read_note, sha256_bytes, write_note


@dataclass(frozen=True)
class AppliedEdit:
    """One rewritten note, keyed by its post-move path."""

    path: str
    before: bytes
    after: bytes

    @property
    def before_sha256(self) -> str:
        return sha256_bytes(self.before)

    @property
    def after_sha256(self) -> str:
        return sha256_bytes(self.after)


@dataclass(frozen=True)
class ApplyResult:
    moves: Tuple[Tuple[str, str], ...]  # (src, dst) pairs actually performed
    edits: Tuple[AppliedEdit, ...]
    move_sha256: Dict[str, str]  # dst path -> sha256 of its final bytes


def _apply_edits_to_text(path: str, text: str, edits: List[LinkEdit]) -> str:
    for edit in sorted(edits, key=lambda e: e.span, reverse=True):
        start, end = edit.span
        current = text[start:end]
        if current != edit.old:
            raise PlanError(
                f"{path} changed between planning and apply "
                f"(expected {edit.old!r} at {start}, found {current!r}); nothing was modified"
            )
        text = text[:start] + edit.new + text[end:]
    return text


def prune_empty_dirs(root: Path, rel_dir: str) -> None:
    """Remove now-empty directories under (and including) ``rel_dir``."""
    base = Path(root) / rel_dir
    if not base.is_dir():
        return
    for dirpath, _dirnames, _filenames in os.walk(base, topdown=False):
        try:
            os.rmdir(dirpath)
        except OSError:
            pass  # not empty (e.g. holds an untracked hidden file): keep it


def apply_plan(root: Path, plan: MovePlan) -> ApplyResult:
    """Apply ``plan``; returns the material the journal records."""
    root = Path(root)
    mapping = plan.mapping

    # Phase 1: compute all new contents up front (no writes yet).
    grouped: Dict[str, List[LinkEdit]] = {}
    for edit in plan.edits:
        grouped.setdefault(edit.path, []).append(edit)
    staged: List[Tuple[str, bytes, bytes]] = []  # (post-move path, before, after)
    for path in sorted(grouped):
        text, before = read_note(root, path)
        after = encode_note(_apply_edits_to_text(path, text, grouped[path]))
        staged.append((mapping.get(path, path), before, after))

    # Phase 2: move files.
    performed: List[Tuple[str, str]] = []
    for move in plan.moves:
        src_abs = root / move.src
        dst_abs = root / move.dst
        if dst_abs.exists():
            raise PlanError(f"destination appeared during apply: {move.dst}")
        dst_abs.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src_abs, dst_abs)
        performed.append((move.src, move.dst))
    if plan.src_is_dir:
        prune_empty_dirs(root, plan.src)

    # Phase 3: write rewritten notes at their new homes.
    applied: List[AppliedEdit] = []
    for path, before, after in staged:
        write_note(root, path, after)
        applied.append(AppliedEdit(path=path, before=before, after=after))

    # Fingerprint every moved file's final bytes so undo can detect edits
    # made after the move even when the file itself was never rewritten.
    move_sha256 = {dst: sha256_bytes((root / dst).read_bytes()) for _src, dst in performed}

    return ApplyResult(moves=tuple(performed), edits=tuple(applied), move_sha256=move_sha256)
