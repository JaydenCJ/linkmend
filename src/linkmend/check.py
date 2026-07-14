"""Read-only diagnostics: broken links and backlinks.

``check`` is the safety net around ``mv``: run it before a reorganization to
see what is already broken, and after to prove the move introduced nothing
new. ``backlinks`` answers "who points here?" before you decide to move a
note at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from .links import INTERNAL, scan_links
from .resolve import AMBIGUOUS, FILE, MISSING, resolve_link
from .vault import VaultIndex, normalize_rel, read_note


@dataclass(frozen=True)
class BrokenLink:
    path: str
    line: int
    raw: str  # the destination / wiki target as written
    kind: str  # "inline" | "refdef" | "wiki"
    reason: str  # "missing" | "ambiguous"
    candidates: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Backlink:
    path: str
    line: int
    raw: str
    kind: str


@dataclass(frozen=True)
class CheckReport:
    broken: Tuple[BrokenLink, ...]
    notes_checked: int
    links_checked: int

    @property
    def files_affected(self) -> int:
        return len({b.path for b in self.broken})


def check_vault(root: Path, index: VaultIndex) -> CheckReport:
    """Resolve every internal link in the vault; collect the failures."""
    broken: List[BrokenLink] = []
    links_checked = 0
    for note in index.md_files:
        text, _ = read_note(root, note)
        for link in scan_links(text):
            if link.classification != INTERNAL:
                continue
            links_checked += 1
            res = resolve_link(link, note, index)
            if res.status == MISSING:
                broken.append(
                    BrokenLink(note, link.line, link.raw.strip(), link.kind, "missing")
                )
            elif res.status == AMBIGUOUS:
                broken.append(
                    BrokenLink(
                        note,
                        link.line,
                        link.raw.strip(),
                        link.kind,
                        "ambiguous",
                        candidates=res.candidates,
                    )
                )
    return CheckReport(
        broken=tuple(broken),
        notes_checked=len(index.md_files),
        links_checked=links_checked,
    )


def find_backlinks(root: Path, index: VaultIndex, target_arg: str) -> List[Backlink]:
    """Every link in the vault that resolves to ``target_arg``."""
    target = normalize_rel(root, target_arg)
    if not index.has_file(target) and index.has_file(target + ".md"):
        target += ".md"
    hits: List[Backlink] = []
    for note in index.md_files:
        text, _ = read_note(root, note)
        for link in scan_links(text):
            if link.classification != INTERNAL:
                continue
            res = resolve_link(link, note, index)
            if res.status == FILE and res.path == target:
                hits.append(Backlink(note, link.line, link.raw.strip(), link.kind))
    return hits
