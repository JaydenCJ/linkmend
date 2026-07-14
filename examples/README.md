# linkmend examples

Two ways to try linkmend without touching your own notes:

- **`sample-vault/`** — a miniature knowledge base with every link style
  linkmend understands: relative Markdown paths, anchors, titles,
  reference definitions, wiki links with aliases, an image attachment,
  and a link inside a code fence (which must never be touched).
- **`reorganize.sh`** — copies the sample vault to a temp directory and
  walks through the full workflow: `check` → `mv --dry-run` → `mv` →
  `check` → `backlinks` → `undo` → `check`, asserting the vault ends up
  byte-identical to how it started.

Run it from the repository root (stdlib only, no install needed):

```bash
bash examples/reorganize.sh
```

The script prints each command before running it, so it doubles as a
cheat sheet for the CLI. It never modifies `sample-vault/` itself — the
copy lives in `mktemp -d` and is deleted on exit.
