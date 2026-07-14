# Journal format (version 1)

Every applied `linkmend mv` writes one transaction file to
`.linkmend/journal/NNNN.json` inside the vault (`0001.json`, `0002.json`,
…). The journal is deliberately plain JSON: human-inspectable, greppable,
diff-able, and safe to delete once you trust a reorganization.

## Transaction schema

```json
{
  "journal_version": 1,
  "id": 1,
  "created_at": "2026-07-12T09:30:00Z",
  "command": "mv Projects/Alpha.md Archive/Alpha.md",
  "moves": [
    { "from": "Projects/Alpha.md", "to": "Archive/Alpha.md", "sha256": "…hex…" }
  ],
  "edits": [
    {
      "path": "index.md",
      "before_sha256": "…hex…",
      "after_sha256": "…hex…",
      "encoding": "utf-8",
      "before": "the full pre-rewrite content of index.md"
    }
  ],
  "stats": { "files_moved": 1, "files_edited": 1 },
  "undone": false,
  "undone_at": ""
}
```

Field notes:

- **All paths are vault-relative POSIX strings**, so a journal survives the
  vault being synced between machines or renamed.
- **`edits[].path` is the post-move location.** A note that was both moved
  and rewritten is recorded where it ended up; undo restores content there
  first, then moves the file back, carrying the restored bytes with it.
- **`before` is the complete pre-image**, not a diff — undo must be exact
  even if a later tool re-wraps the file. Notes that decode as UTF-8 are
  stored as text (`"encoding": "utf-8"`); anything else is stored
  losslessly as `"encoding": "base64"`.
- **`before_sha256` / `after_sha256`** fingerprint the raw bytes. `undo`
  recomputes the current hash of every touched file and compares it to
  `after_sha256`; any mismatch means something else edited the file since,
  and the undo is refused with a per-file conflict list (`--force`
  overrides).
- **`moves[].sha256`** fingerprints each moved file's final bytes, so a
  file that was only relocated (never rewritten) is verified the same way;
  entries written without it are skipped by verification.
- **`undone`** flips to `true` in place when the transaction is reversed
  (with `undone_at` set), so `linkmend log` shows accurate history and a
  transaction can never be undone twice.

## Guarantees and non-guarantees

- Writing is atomic per file (temp file + `os.replace`); a crash mid-`mv`
  can leave the move partially applied but never a half-written note, and
  the journal entry is only created after the whole apply succeeded.
- The journal grows by roughly the size of the rewritten notes per
  transaction. There is no automatic pruning in 0.1.0 — `rm -rf
  .linkmend/journal` is the supported way to start fresh.
- `undo` reverses one transaction. Undoing several means undoing them
  newest-first (the CLI picks the newest active one by default), which
  keeps the hash verification meaningful at every step.
