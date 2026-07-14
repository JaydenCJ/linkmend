# Contributing to linkmend

Thanks for your interest in contributing. Issues, discussions, and pull
requests are all welcome.

## Getting started

You need Python ≥ 3.9. Nothing else — the runtime is standard-library only.

```bash
git clone https://github.com/JaydenCJ/linkmend
cd linkmend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                 # 90 tests, all offline, sub-second
bash scripts/smoke.sh  # end-to-end: build a vault, mv, check, undo
```

`scripts/smoke.sh` reorganizes a throwaway vault with the real CLI and
verifies the undo restores it byte-for-byte; it must print `SMOKE OK`.

## Before you open a pull request

1. `python3 -m compileall -q src` — must be clean (no syntax debt).
2. `pytest` — must pass; add tests for any behavior change.
3. `bash scripts/smoke.sh` — must print `SMOKE OK`.
4. Keep logic in the pure modules (`links`, `resolve`, `rewrite`, `plan`)
   and side effects in `apply`/`journal`; the CLI stays a thin shell.
5. Rewrite behavior changes must update `docs/link-rules.md`; journal
   field changes must bump `journal_version` and update
   `docs/journal-format.md` in the same pull request.

## Ground rules

- **No runtime dependencies, ever.** That is the product. Test-only
  dependencies belong in the `dev` extra and need justification in the PR.
- **Never lose user data.** Every code path that writes must either be
  journaled, atomic, or refuse to run — a wrong answer that is undoable
  beats a right answer that is not reversible.
- No network calls, no telemetry; linkmend only touches the vault it is
  pointed at.
- Code comments and doc comments are written in English.
- Keep the three READMEs aligned: `README.md`, `README.zh.md`, and
  `README.ja.md` are line-for-line parallel (English is authoritative).

## Reporting bugs

Include `linkmend --version`, the exact command, the `--json` output if
possible, and a minimal vault layout (a handful of files with their links)
that reproduces the problem. If a `mv` produced a wrong rewrite, the
journal entry under `.linkmend/journal/` shows exactly what was changed
and is the perfect attachment.

## Security

Please do not open public issues for security-relevant problems (e.g.
path-escape bugs that could write outside a vault); use GitHub's private
vulnerability reporting on the repository instead.
