#!/usr/bin/env bash
# Walk through the full linkmend workflow on a *copy* of the sample vault:
#   check -> mv --dry-run -> mv -> check -> backlinks -> undo -> check
# and prove the undo restored every byte. Safe to run repeatedly.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/linkmend-example.XXXXXX")"
trap 'rm -rf "$WORKDIR"' EXIT
cp -R "$ROOT/examples/sample-vault" "$WORKDIR/vault"
VAULT="$WORKDIR/vault"

run() {
  echo
  echo "\$ linkmend $*"
  "$PYTHON" -m linkmend "$@" --vault "$VAULT"
}

fingerprint() {
  (cd "$VAULT" && find . -type f ! -path './.linkmend/*' | sort | xargs sha256sum)
}

BEFORE="$(fingerprint)"

run check
run mv Projects/Alpha.md "Archive/2026/Alpha (shipped).md" --dry-run
run mv Projects/Alpha.md "Archive/2026/Alpha (shipped).md"
run check
run backlinks "Archive/2026/Alpha (shipped).md"
run log
run undo

echo
if [ "$(fingerprint)" = "$BEFORE" ]; then
  echo "undo verified: the vault is byte-identical to where we started"
else
  echo "ERROR: vault differs after undo" >&2
  exit 1
fi
run check
