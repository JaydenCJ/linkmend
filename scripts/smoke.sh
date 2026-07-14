#!/usr/bin/env bash
# Smoke test for linkmend: build a small vault, reorganize it with `mv`,
# prove zero links break, then `undo` and prove the vault is byte-identical.
# Self-contained: pure stdlib, no network, idempotent (works from a clean tree).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

# Zero runtime dependencies, so running from src/ needs no install.
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/linkmend-smoke.XXXXXX")"
trap 'rm -rf "$WORKDIR"' EXIT

fail() { echo "SMOKE FAIL: $1" >&2; exit 1; }

echo "[smoke] python: $("$PYTHON" --version 2>&1)"

# 0. Build a realistic vault: nested notes, wiki links, an attachment,
#    a reference definition, and a link inside a code fence (must survive).
VAULT="$WORKDIR/vault"
mkdir -p "$VAULT/Projects" "$VAULT/assets"
cat > "$VAULT/index.md" <<'EOF'
# Index

- [Alpha project](Projects/Alpha.md)
- [Kickoff](Projects/Alpha.md#kickoff "notes")
- [[Alpha]] and ![logo](assets/logo.png)

[alpha-ref]: Projects/Alpha.md

```bash
cat Projects/Alpha.md   # inside a fence: never touched
```
EOF
cat > "$VAULT/Projects/Alpha.md" <<'EOF'
# Alpha

Back to [index](../index.md). See [[Beta]] and ![](../assets/logo.png).
EOF
cat > "$VAULT/Projects/Beta.md" <<'EOF'
Sibling: [Alpha](Alpha.md), extensionless [Alpha](./Alpha).
EOF
printf 'not-a-real-png' > "$VAULT/assets/logo.png"
BEFORE="$(cd "$VAULT" && find . -type f ! -path './.linkmend/*' | sort | xargs sha256sum)"

# 1. A clean vault checks clean.
check_out="$("$PYTHON" -m linkmend check --vault "$VAULT")"
echo "$check_out" | sed 's/^/[check] /'
echo "$check_out" | grep -q "no broken links" || fail "baseline vault should be clean"

# 2. Dry run prints a plan and writes nothing.
dry_out="$("$PYTHON" -m linkmend mv Projects/Alpha.md "Archive/2026/Alpha (done).md" --dry-run --vault "$VAULT")"
echo "$dry_out" | sed 's/^/[dry] /'
echo "$dry_out" | grep -q "dry run, nothing written" || fail "dry run banner missing"
[ -f "$VAULT/Projects/Alpha.md" ] || fail "dry run must not move files"
[ ! -d "$VAULT/.linkmend" ] || fail "dry run must not write a journal"

# 3. Real move: file relocated, every link rewritten, vault still clean.
mv_out="$("$PYTHON" -m linkmend mv Projects/Alpha.md "Archive/2026/Alpha (done).md" --vault "$VAULT")"
echo "$mv_out" | sed 's/^/[mv] /'
echo "$mv_out" | grep -q "transaction #1" || fail "mv did not record transaction #1"
[ -f "$VAULT/Archive/2026/Alpha (done).md" ] || fail "note not moved"
grep -q "<Archive/2026/Alpha (done).md>" "$VAULT/index.md" || fail "inbound link not rewritten"
grep -q 'cat Projects/Alpha.md' "$VAULT/index.md" || fail "code fence was modified"
"$PYTHON" -m linkmend check --vault "$VAULT" >/dev/null || fail "links broke after mv"

# 4. Backlinks finds the rewritten references.
back_out="$("$PYTHON" -m linkmend backlinks "Archive/2026/Alpha (done).md" --vault "$VAULT")"
echo "$back_out" | sed 's/^/[backlinks] /'
echo "$back_out" | grep -q "backlinks from" || fail "backlinks summary missing"

# 5. Folder move on top, then check again.
"$PYTHON" -m linkmend mv Projects attic/projects --vault "$VAULT" >/dev/null \
  || fail "folder move failed"
"$PYTHON" -m linkmend check --vault "$VAULT" >/dev/null || fail "links broke after folder move"

# 6. Undo twice (newest first) restores the vault byte-for-byte.
"$PYTHON" -m linkmend undo --vault "$VAULT" | sed 's/^/[undo] /'
"$PYTHON" -m linkmend undo --vault "$VAULT" | sed 's/^/[undo] /'
AFTER="$(cd "$VAULT" && find . -type f ! -path './.linkmend/*' | sort | xargs sha256sum)"
[ "$BEFORE" = "$AFTER" ] || fail "undo did not restore the vault byte-for-byte"

# 7. A third undo has nothing left to do and exits 2.
set +e
"$PYTHON" -m linkmend undo --vault "$VAULT" >/dev/null 2>&1
rc=$?
set -e
[ "$rc" -eq 2 ] || fail "undo on an empty journal should exit 2, got $rc"

# 8. Journal survives as inspectable history.
log_out="$("$PYTHON" -m linkmend log --vault "$VAULT")"
echo "$log_out" | sed 's/^/[log] /'
echo "$log_out" | grep -q "(undone)" || fail "log missing undone marker"

# 9. --version agrees with the package version.
version_out="$("$PYTHON" -m linkmend --version)"
pkg_version="$("$PYTHON" -c 'import linkmend; print(linkmend.__version__)')"
[ "$version_out" = "linkmend $pkg_version" ] \
  || fail "--version mismatch: '$version_out' vs package '$pkg_version'"

echo "SMOKE OK"
