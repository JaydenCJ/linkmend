# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-12

### Added

- `linkmend mv`: move or rename a note, attachment, or whole folder while
  rewriting every affected link vault-wide — inbound links from other
  notes, the moved note's own outbound relative links, and links between
  co-moved files (which correctly produce no churn). Unix `mv` destination
  semantics (existing directory nests; trailing slash forces a directory).
- Link scanner covering inline links/images (plain, `<angle>`, titles,
  percent-encoding, backslash escapes, balanced parentheses), reference
  definitions, and wiki links/embeds with anchors and aliases; fenced code
  blocks and inline code spans are masked and never touched.
- Obsidian-compatible wiki-name resolution: bare names anywhere in the
  vault, path-suffix disambiguation, exact-case first with case-insensitive
  fallback, and honest `ambiguous` handling (reported, never guessed).
- Style-preserving rewriter: relative/vault-absolute, `./` prefixes,
  trailing slashes, encodings, angle brackets, extensionless links, and
  bare wiki names that widen to paths only when a rename forces it.
- Undo journal (`.linkmend/journal/NNNN.json`): every `mv` is a numbered
  transaction storing file moves plus byte-exact pre-images and SHA-256
  before/after fingerprints; `linkmend undo` verifies the vault is
  unchanged since (per-file conflict list, `--force` to override) and
  restores it byte-for-byte; `linkmend log` lists history newest-first.
- `linkmend check`: broken- and ambiguous-link report with `file:line`
  locations, exit code 1 for CI gates; `linkmend backlinks`: every link
  resolving to a note.
- `--dry-run` on `mv` and `undo`, `--json` envelopes on every subcommand
  (stable `tool`/`version` fields), one-line errors and a 0/1/2 exit-code
  contract.
- Safety rails: pure planning (dry run is the real plan), a pre-apply span
  check that aborts before touching anything if a note changed since
  planning, atomic per-file writes, non-UTF-8 notes preserved losslessly,
  and refusal to move into hidden directories the index cannot see.
- Runnable sample vault and workflow script under `examples/`, format
  documentation in `docs/link-rules.md` and `docs/journal-format.md`.
- 90 offline pytest tests and `scripts/smoke.sh` (build vault → mv →
  check → backlinks → folder mv → double undo → byte-identical assert).

### Notes

- The repository ships no CI workflow; verification is local — `pip install -e '.[dev]' && pytest && bash scripts/smoke.sh`.

[0.1.0]: https://github.com/JaydenCJ/linkmend/releases/tag/v0.1.0
