# Link rules: what linkmend parses, resolves, and rewrites

This is the authoritative description of linkmend's link model. If behavior
and this document disagree, that is a bug — please report it.

## Recognized syntaxes

| Syntax | Example | Rewritten part |
|---|---|---|
| Inline link | `[text](notes/api.md "title")` | destination only; text and title untouched |
| Image | `![alt](assets/logo.png)` | destination only |
| Angle destination | `[text](<my note.md>)` | destination, brackets preserved |
| Reference definition | `[api]: notes/api.md` | destination only; label untouched |
| Wiki link | `[[Note#Heading\|alias]]` | target only; anchor and alias untouched |
| Wiki embed | `![[diagram.png]]` | target only |

Reference-style *usages* (`[text][api]`) carry no path, so only the
definition line is ever edited. Autolinks (`<https://…>`) are external by
definition and ignored.

## What is skipped

- **External targets**: any scheme (`https:`, `mailto:`, …) or
  protocol-relative `//host/...`.
- **Anchor-only links**: `[…](#heading)` and `[[#Heading]]`.
- **Code**: fenced blocks (``` and `~~~`, CommonMark length/marker rules)
  and inline code spans (backtick runs, matched by equal length). Links
  inside them are never parsed, checked, or rewritten.
- **Hidden files and directories** (leading `.`): invisible to the index,
  which conveniently excludes `.git`, `.obsidian`, and `.linkmend` itself.

Known limitation: **indented code blocks** (4-space) are treated as prose,
because recognizing them requires full block-level parsing (blank-line and
paragraph context). Use fenced blocks for code containing link-like text —
the common convention in every vault app. Escaped brackets inside link text
and links split across lines are also out of scope for 0.1.0.

## Resolution

Markdown paths resolve like a filesystem:

1. `/`-prefixed → from the vault root (`/notes/api.md`).
2. Otherwise → relative to the note containing the link.
3. Percent-escapes (`my%20note.md`) and backslash escapes (`my\ note.md`)
   are decoded first.
4. If the exact path is not a file, `.md` is appended and tried again.
5. A path that resolves to a directory is a *directory link* (valid; it is
   rewritten when that directory moves).
6. Anything escaping the vault root is unresolvable — reported by `check`,
   never rewritten.

Wiki names resolve like Obsidian:

1. The name matches a file's full vault path or a path *suffix*, with the
   extension spelled out (`[[api.md]]`, `[[img.png]]`) or without it for
   notes (`[[api]]`, `[[guides/Setup]]`).
2. Exact-case matches win; if there are none, a case-insensitive pass runs.
3. Exactly one match → resolved. Multiple → **ambiguous**: `check` reports
   it with all candidates, and `mv` refuses to rewrite it (a rewrite based
   on a guess could silently flip which note the link points at).

## Rewriting: style preservation

The rewriter recomputes the target from the post-move locations of *both*
ends of the link, then re-renders it in the author's original style:

- relative stays relative, vault-absolute keeps its leading `/`;
- a `./` prefix survives; a trailing `/` on directory links survives;
- percent-encoded destinations are re-encoded (`Alpha (final).md` →
  `Alpha%20%28final%29.md`); plain destinations that gain a space or
  parenthesis switch to `<angle brackets>`;
- extensionless links stay extensionless; explicit `[[Note.md]]` keeps
  its extension; attachments keep theirs;
- bare wiki names stay bare while unique vault-wide, and widen to a
  vault-relative path the moment a rename would make them ambiguous;
- anchors, aliases, and titles are outside the rewrite span and cannot be
  altered, by construction.

A link is only edited when the rendered result actually differs — a note
moving *with* its neighbors produces no churn in the links between them.
