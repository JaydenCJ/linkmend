"""Markdown and wiki link scanner.

Finds every rewritable link in a note and records the exact byte span of the
part linkmend may replace, so a rewrite touches nothing else — not the link
text, not the alias, not the title, not surrounding prose.

Recognized syntaxes:

- inline links and images: ``[text](target)``, ``![alt](target "title")``,
  angle-bracket destinations ``[t](<a file.md>)``;
- reference definitions: ``[label]: target "title"``;
- wiki links and embeds: ``[[Note]]``, ``[[Note#heading|alias]]``, ``![[img.png]]``.

Fenced code blocks (backtick and tilde) and inline code spans are masked out
first, so a link-looking string inside code is never touched. Indented code
blocks are deliberately *not* masked — see docs/link-rules.md for why.
"""

from __future__ import annotations

import bisect
import re
import urllib.parse
from dataclasses import dataclass
from typing import List, Tuple

#: URI schemes make a target external; ``//host`` (protocol-relative) too.
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
_WIKI_RE = re.compile(
    r"\[\[(?!\[)"
    r"(?P<target>[^\[\]|#\n]*)"
    r"(?P<anchor>#[^\[\]|\n]*)?"
    r"(?P<alias>\|[^\[\]\n]*)?"
    r"\]\]"
)
_REFDEF_RE = re.compile(r"^ {0,3}\[[^\]\n]+\]:[ \t]*(?P<dest><[^<>\n]*>|\S+)")
_ESCAPE_RE = re.compile(r"\\([ !-/:-@\[-`{-~])")

EXTERNAL = "external"
ANCHOR = "anchor"
INTERNAL = "internal"


@dataclass(frozen=True)
class Link:
    """One rewritable link occurrence inside a note.

    ``span`` covers exactly the text a rewrite would replace: the whole
    destination token for Markdown links (including ``<...>`` if used) and
    the bare target for wiki links (anchor and alias live outside the span).
    """

    kind: str  # "inline" | "refdef" | "wiki"
    span: Tuple[int, int]
    raw: str  # exact source text within span
    target: str  # decoded path portion ("" if anchor-only)
    anchor: str  # includes leading "#", or ""
    line: int  # 1-based line number of the destination
    angle: bool  # Markdown destination was wrapped in <...>
    encoded: bool  # path portion used percent-escapes

    @property
    def classification(self) -> str:
        """external / anchor / internal — only internal links are rewritten."""
        if not self.target:
            return ANCHOR if self.anchor else EXTERNAL
        if _SCHEME_RE.match(self.target) or self.target.startswith("//"):
            return EXTERNAL
        return INTERNAL


def _line_starts(text: str) -> List[int]:
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _mask_regions(text: str) -> bytearray:
    """Return a mask marking code positions (fenced blocks + inline spans)."""
    mask = bytearray(len(text))
    lines = text.split("\n")
    offset = 0
    fence: Tuple[str, int] = ("", 0)  # (char, length) of the open fence
    for line in lines:
        m = _FENCE_RE.match(line)
        if fence[0]:
            mask[offset : offset + len(line) + 1] = b"\x01" * (len(line) + 1)
            if m and m.group(2)[0] == fence[0] and len(m.group(2)) >= fence[1] and not m.group(3).strip():
                fence = ("", 0)
        elif m and not (m.group(2)[0] == "`" and "`" in m.group(3)):
            fence = (m.group(2)[0], len(m.group(2)))
            mask[offset : offset + len(line) + 1] = b"\x01" * (len(line) + 1)
        offset += len(line) + 1
    # Inline code spans on unfenced text: a run of N backticks opens a span
    # closed by the next run of exactly N backticks (CommonMark rule).
    runs = [
        (m.start(), m.end())
        for m in re.finditer(r"`+", text)
        if not mask[m.start()]
    ]
    i = 0
    while i < len(runs):
        start, end = runs[i]
        length = end - start
        for j in range(i + 1, len(runs)):
            cstart, cend = runs[j]
            if cend - cstart == length:
                mask[start:cend] = b"\x01" * (cend - start)
                i = j
                break
        i += 1
    return mask


def _unescape(dest: str) -> str:
    """Undo Markdown backslash escapes (``foo\\ bar.md`` → ``foo bar.md``)."""
    return _ESCAPE_RE.sub(r"\1", dest)


def _split_destination(raw: str) -> Tuple[str, str, bool]:
    """Split a raw destination into (decoded path, anchor, was-encoded)."""
    if "#" in raw:
        path_raw, _, frag = raw.partition("#")
        anchor = "#" + frag
    else:
        path_raw, anchor = raw, ""
    unescaped = _unescape(path_raw)
    decoded = urllib.parse.unquote(unescaped)
    return decoded, anchor, decoded != unescaped


def _scan_inline(text: str, mask: bytearray, starts: List[int], out: List[Link]) -> None:
    n = len(text)
    pos = 0
    while True:
        i = text.find("](", pos)
        if i == -1:
            return
        pos = i + 2
        if mask[i]:
            continue
        j = i + 2
        while j < n and text[j] in " \t":
            j += 1
        if j >= n:
            continue
        angle = text[j] == "<"
        if angle:
            close = text.find(">", j + 1)
            newline = text.find("\n", j + 1)
            if close == -1 or (newline != -1 and newline < close):
                continue
            dest_span = (j, close + 1)
            raw_dest = text[j + 1 : close]
            after = close + 1
        else:
            depth = 0
            k = j
            while k < n:
                c = text[k]
                if c in " \t\n":
                    break
                if c == "\\":
                    k += 2
                    continue
                if c == "(":
                    depth += 1
                elif c == ")":
                    if depth == 0:
                        break
                    depth -= 1
                k += 1
            dest_span = (j, k)
            raw_dest = text[j:k]
            after = k
        m = after
        while m < n and text[m] in " \t":
            m += 1
        if m < n and text[m] in "\"'":
            quote = text[m]
            m += 1
            while m < n and text[m] != quote:
                m += 2 if text[m] == "\\" else 1
            if m >= n:
                continue
            m += 1
            while m < n and text[m] in " \t":
                m += 1
        if m >= n or text[m] != ")" or not raw_dest:
            continue
        path, anchor, encoded = _split_destination(raw_dest)
        out.append(
            Link(
                kind="inline",
                span=dest_span,
                raw=text[dest_span[0] : dest_span[1]],
                target=path,
                anchor=anchor,
                line=bisect.bisect_right(starts, dest_span[0]),
                angle=angle,
                encoded=encoded,
            )
        )
        pos = m + 1


def _scan_refdefs(text: str, mask: bytearray, starts: List[int], out: List[Link]) -> None:
    offset = 0
    for line in text.split("\n"):
        m = _REFDEF_RE.match(line)
        if m and not mask[offset]:
            raw_dest = m.group("dest")
            angle = raw_dest.startswith("<")
            inner = raw_dest[1:-1] if angle else raw_dest
            span = (offset + m.start("dest"), offset + m.end("dest"))
            if inner:
                path, anchor, encoded = _split_destination(inner)
                out.append(
                    Link(
                        kind="refdef",
                        span=span,
                        raw=raw_dest,
                        target=path,
                        anchor=anchor,
                        line=bisect.bisect_right(starts, span[0]),
                        angle=angle,
                        encoded=encoded,
                    )
                )
        offset += len(line) + 1


def _scan_wiki(text: str, mask: bytearray, starts: List[int], out: List[Link]) -> None:
    for m in _WIKI_RE.finditer(text):
        if mask[m.start()]:
            continue
        span = (m.start("target"), m.end("target"))
        raw = m.group("target")
        out.append(
            Link(
                kind="wiki",
                span=span,
                raw=raw,
                target=raw.strip(),
                anchor=m.group("anchor") or "",
                line=bisect.bisect_right(starts, m.start()),
                angle=False,
                encoded=False,
            )
        )


def scan_links(text: str) -> List[Link]:
    """Find every link in ``text``, sorted by position, code masked out."""
    mask = _mask_regions(text)
    starts = _line_starts(text)
    out: List[Link] = []
    _scan_inline(text, mask, starts, out)
    _scan_refdefs(text, mask, starts, out)
    _scan_wiki(text, mask, starts, out)
    out.sort(key=lambda l: l.span)
    return out
