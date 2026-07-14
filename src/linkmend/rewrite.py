"""Compute replacement text for a link whose source or target moved.

The golden rule: **preserve the author's style**. A relative path stays
relative, a vault-absolute path keeps its leading ``/``, a ``./`` prefix
survives, percent-encoding stays percent-encoded, an angle-bracket
destination keeps its brackets, an extension-less link stays extension-less,
and a bare wiki name stays bare as long as it is still unambiguous. Anchors,
aliases, and titles are never inside the rewrite span, so they survive by
construction.
"""

from __future__ import annotations

import posixpath
import urllib.parse
from typing import Dict

from .links import Link
from .resolve import Resolution
from .vault import is_markdown, strip_md_extension

#: RFC 3986 unreserved + path characters we keep readable when re-encoding.
_QUOTE_SAFE = "/!$&'*+,;=:@-._~"


def _needs_protection(dest: str) -> bool:
    """A plain Markdown destination cannot contain whitespace or parens."""
    return any(ch in dest for ch in " \t()")


def rewrite_md_destination(
    link: Link,
    new_source_rel: str,
    new_target_rel: str,
    resolution: Resolution,
) -> str:
    """Return the full destination token that replaces ``link.span``.

    ``new_source_rel``/``new_target_rel`` are the post-move locations of the
    note containing the link and the file it points at.
    """
    path = new_target_rel
    if resolution.via_md_ext:
        path = strip_md_extension(path)
    if link.target.startswith("/"):
        new_path = "/" + path
    else:
        base = posixpath.dirname(new_source_rel) or "."
        new_path = posixpath.relpath(path, base)
        if link.target.startswith("./") and not new_path.startswith("."):
            new_path = "./" + new_path
    if link.target.endswith("/") and not new_path.endswith("/"):
        new_path += "/"  # directory links keep their trailing slash
    if link.encoded:
        return urllib.parse.quote(new_path, safe=_QUOTE_SAFE) + link.anchor
    dest = new_path + link.anchor
    if link.angle or _needs_protection(dest):
        return f"<{dest}>"
    return dest


def rewrite_wiki_target(
    link: Link,
    new_target_rel: str,
    stem_counts: Dict[str, int],
) -> str:
    """Return the new wiki target (the text between ``[[`` and ``#``/``|``).

    ``stem_counts`` is the post-move census from
    :func:`linkmend.vault.stems_after_move`; a bare name is kept bare only
    while it stays unique across the whole vault.
    """
    target_is_md = is_markdown(new_target_rel)
    keep_ext = link.target.lower().endswith((".md", ".markdown"))
    if target_is_md and not keep_ext:
        display = strip_md_extension(new_target_rel)
    else:
        display = new_target_rel
    base = posixpath.basename(display)
    stem_key = posixpath.basename(
        strip_md_extension(new_target_rel) if target_is_md else new_target_rel
    ).lower()
    if "/" in link.target or stem_counts.get(stem_key, 0) > 1:
        return display  # path style in, path style out; or forced by a tie
    return base
