"""Plan a move: which files relocate, and which links must be rewritten.

Planning is pure — it reads the vault but changes nothing, which is what
makes ``--dry-run`` trustworthy: the printed plan *is* the exact edit list
that ``apply`` would execute.

A plan covers three link populations:

1. links in **other notes** pointing at anything that moves;
2. links **inside moved notes** pointing at things that stay (their relative
   base changed);
3. links **between two moved files** (both ends changed; often the relative
   path is unchanged and no edit is emitted).
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

from .errors import PlanError
from .links import Link, scan_links
from .resolve import DIR, FILE, resolve_link
from .rewrite import rewrite_md_destination, rewrite_wiki_target
from .vault import VaultIndex, normalize_rel, read_note, stems_after_move


@dataclass(frozen=True)
class FileMove:
    src: str
    dst: str


@dataclass(frozen=True)
class LinkEdit:
    """One span replacement in one note (path is the pre-move location)."""

    path: str
    line: int
    span: Tuple[int, int]
    old: str
    new: str


@dataclass
class MovePlan:
    src: str
    dst: str
    src_is_dir: bool
    moves: List[FileMove] = field(default_factory=list)
    edits: List[LinkEdit] = field(default_factory=list)

    @property
    def mapping(self) -> Dict[str, str]:
        return {m.src: m.dst for m in self.moves}

    @property
    def files_moved(self) -> int:
        return len(self.moves)

    @property
    def links_rewritten(self) -> int:
        return len(self.edits)

    @property
    def files_edited(self) -> int:
        return len({e.path for e in self.edits})

    def command_line(self) -> str:
        return f"mv {self.src} {self.dst}"


def _build_mapping(
    root: Path, index: VaultIndex, src_arg: str, dst_arg: str
) -> Tuple[str, str, bool, Dict[str, str], Dict[str, str]]:
    """Validate arguments and map every moved file (and dir) to its new path."""
    src = normalize_rel(root, src_arg)
    src_abs = root / src
    if not src_abs.exists():
        raise PlanError(f"source not found in vault: {src}")
    src_is_dir = src_abs.is_dir()

    dst = normalize_rel(root, dst_arg)
    into_dir = dst_arg.replace("\\", "/").endswith("/") or (root / dst).is_dir()
    if into_dir:
        dst = posixpath.normpath(f"{dst}/{posixpath.basename(src)}")
    if dst.split("/", 1)[0].startswith("."):
        raise PlanError(f"destination is inside a hidden directory linkmend ignores: {dst}")
    if dst == src:
        raise PlanError(f"source and destination are the same: {src}")
    if src_is_dir and (dst == src or dst.startswith(src + "/")):
        raise PlanError(f"cannot move a directory into itself: {src} -> {dst}")

    mapping: Dict[str, str] = {}
    dir_mapping: Dict[str, str] = {}
    if src_is_dir:
        for f in index.files:
            if f == src or f.startswith(src + "/"):
                mapping[f] = dst + f[len(src) :]
        dir_mapping[src] = dst
        for d in sorted(index.dirs):
            if d.startswith(src + "/"):
                dir_mapping[d] = dst + d[len(src) :]
        if not mapping:
            raise PlanError(f"directory contains no files linkmend tracks: {src}")
    else:
        mapping[src] = dst

    conflicts = sorted(
        new for new in mapping.values() if index.has_file(new) and new not in mapping
    )
    for new in mapping.values():
        if (root / new).exists() and new not in mapping:
            if new not in conflicts:
                conflicts.append(new)
    if conflicts:
        listing = ", ".join(conflicts[:5])
        raise PlanError(f"destination already exists: {listing}")
    return src, dst, src_is_dir, mapping, dir_mapping


def _plan_one_link(
    link: Link,
    note: str,
    new_note: str,
    index: VaultIndex,
    mapping: Dict[str, str],
    dir_mapping: Dict[str, str],
    stem_counts: Dict[str, int],
) -> str:
    """Return the replacement text for ``link``, or "" when nothing changes."""
    res = resolve_link(link, note, index)
    if res.status not in (FILE, DIR):
        return ""  # external, anchor-only, missing, or ambiguous: never touched
    if link.kind == "wiki":
        # Wiki names are location-independent: only a *target* move matters.
        if res.status != FILE or res.path not in mapping:
            return ""
        new = rewrite_wiki_target(link, mapping[res.path], stem_counts)
        if new.lower() == link.target.lower():
            return ""  # e.g. case-insensitive hit whose name did not change
        return new
    lookup = mapping if res.status == FILE else dir_mapping
    target_new = lookup.get(res.path)
    note_moved = new_note != note
    if target_new is None:
        if not note_moved or link.target.startswith("/"):
            return ""  # vault-absolute links do not care where the note lives
        target_new = res.path
    new = rewrite_md_destination(link, new_note, target_new, res)
    return "" if new == link.raw else new


def plan_move(root: Path, index: VaultIndex, src_arg: str, dst_arg: str) -> MovePlan:
    """Build the full move plan; raises :class:`PlanError` on any conflict."""
    src, dst, src_is_dir, mapping, dir_mapping = _build_mapping(
        root, index, src_arg, dst_arg
    )
    plan = MovePlan(src=src, dst=dst, src_is_dir=src_is_dir)
    plan.moves = [FileMove(s, d) for s, d in sorted(mapping.items())]
    stem_counts = stems_after_move(index, mapping)

    for note in index.md_files:
        new_note = mapping.get(note, note)
        text, _ = read_note(root, note)
        for link in scan_links(text):
            new = _plan_one_link(
                link, note, new_note, index, mapping, dir_mapping, stem_counts
            )
            if new:
                plan.edits.append(
                    LinkEdit(path=note, line=link.line, span=link.span, old=link.raw, new=new)
                )
    plan.edits.sort(key=lambda e: (e.path, e.span))
    return plan
