"""Resolve link targets to actual vault files.

Two very different worlds meet here:

- **Markdown paths** resolve like the filesystem does: relative to the note
  that contains them, or vault-absolute when they start with ``/``. A
  missing extension tries ``.md`` (the style GitHub and most editors accept).
- **Wiki names** resolve like Obsidian does: by note name anywhere in the
  vault, with a path suffix (``[[guides/Setup]]``) to disambiguate, exact
  case first and a case-insensitive fallback second. Two notes sharing a
  bare name make the link *ambiguous* — reported by ``check``, never
  silently rewritten by ``mv``.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from typing import Tuple

from .links import ANCHOR, EXTERNAL, INTERNAL, Link
from .vault import VaultIndex, is_markdown, strip_md_extension

FILE = "file"
DIR = "dir"
MISSING = "missing"
AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class Resolution:
    """Outcome of resolving one link against the vault index."""

    status: str  # file | dir | missing | ambiguous | external | anchor
    path: str = ""  # vault-relative path when status is file/dir
    candidates: Tuple[str, ...] = ()  # the tie when status is ambiguous
    via_md_ext: bool = False  # a Markdown path resolved by appending .md


def _resolve_md_path(source_rel: str, target: str, index: VaultIndex) -> Resolution:
    if target.startswith("/"):
        base = posixpath.normpath(target.lstrip("/"))
    else:
        base = posixpath.normpath(posixpath.join(posixpath.dirname(source_rel), target))
    if base.startswith("../") or base == "..":
        return Resolution(MISSING)  # escapes the vault: nothing we can mend
    if base == ".":
        return Resolution(DIR, path=".")
    if index.has_file(base):
        return Resolution(FILE, path=base)
    if index.has_file(base + ".md"):
        return Resolution(FILE, path=base + ".md", via_md_ext=True)
    if index.has_dir(base):
        return Resolution(DIR, path=base)
    return Resolution(MISSING)


def _wiki_matches(name: str, index: VaultIndex, fold_case: bool) -> Tuple[str, ...]:
    probe = name.lower() if fold_case else name
    hits = []
    for f in index.files:
        cand = f.lower() if fold_case else f
        # Match the full path or a path suffix, with the extension spelled
        # out ([[img.png]], [[Note.md]]) ...
        if cand == probe or cand.endswith("/" + probe):
            hits.append(f)
            continue
        # ... or the extension-free note name ([[Note]], [[guides/Setup]]).
        if is_markdown(f):
            stem = strip_md_extension(cand)
            if stem == probe or stem.endswith("/" + probe):
                hits.append(f)
    return tuple(sorted(set(hits)))


def _resolve_wiki_name(name: str, index: VaultIndex) -> Resolution:
    name = name.strip().strip("/")
    if not name:
        return Resolution(MISSING)
    matches = _wiki_matches(name, index, fold_case=False)
    if not matches:
        matches = _wiki_matches(name, index, fold_case=True)
    if len(matches) == 1:
        return Resolution(FILE, path=matches[0])
    if len(matches) > 1:
        return Resolution(AMBIGUOUS, candidates=matches)
    return Resolution(MISSING)


def resolve_link(link: Link, source_rel: str, index: VaultIndex) -> Resolution:
    """Resolve ``link`` as it appears in note ``source_rel``."""
    cls = link.classification
    if cls == EXTERNAL:
        return Resolution(EXTERNAL)
    if cls == ANCHOR:
        return Resolution(ANCHOR)
    assert cls == INTERNAL
    if link.kind == "wiki":
        return _resolve_wiki_name(link.target, index)
    return _resolve_md_path(source_rel, link.target, index)
