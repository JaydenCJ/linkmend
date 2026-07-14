"""Command line interface.

Subcommands:

- ``linkmend mv <src> <dst>``: move/rename a note or folder, rewriting links.
- ``linkmend check``: list broken and ambiguous links.
- ``linkmend backlinks <note>``: list every link pointing at a note.
- ``linkmend log``: show the undo journal.
- ``linkmend undo [id]``: reverse a transaction.

Exit codes: 0 = success / nothing broken; 1 = findings or a refused undo
(broken links, journal conflicts); 2 = usage or environment errors. Every
subcommand takes ``--vault`` (default: current directory) and ``--json``
for a stable machine-readable envelope. Errors are one readable line on
stderr, never a traceback.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__
from .apply import apply_plan
from .check import check_vault, find_backlinks
from .errors import JournalConflictError, LinkmendError
from .journal import find_transaction, load_transactions, record_transaction, undo_transaction, verify_undo
from .plan import MovePlan, plan_move
from .vault import build_index

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkmend",
        description="Move and rename Markdown notes while rewriting every link; undoable.",
    )
    parser.add_argument("--version", action="version", version=f"linkmend {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="command")

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--vault", default=".", help="vault root (default: current directory)")
        p.add_argument("--json", action="store_true", help="machine-readable output")

    p_mv = sub.add_parser("mv", help="move or rename a note/folder and rewrite all links to it")
    p_mv.add_argument("src", help="note, attachment, or folder to move (vault-relative)")
    p_mv.add_argument("dst", help="new path, or an existing folder to move into")
    p_mv.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    common(p_mv)

    p_check = sub.add_parser("check", help="report broken and ambiguous links (exit 1 if any)")
    common(p_check)

    p_back = sub.add_parser("backlinks", help="list every link that points at a note")
    p_back.add_argument("note", help="target note (vault-relative; .md may be omitted)")
    common(p_back)

    p_log = sub.add_parser("log", help="show the undo journal, newest first")
    p_log.add_argument("--limit", type=int, default=0, help="show at most N transactions")
    common(p_log)

    p_undo = sub.add_parser("undo", help="reverse a transaction (default: the newest active one)")
    p_undo.add_argument("id", nargs="?", type=int, help="transaction id (see `linkmend log`)")
    p_undo.add_argument("--dry-run", action="store_true", help="verify and describe, change nothing")
    p_undo.add_argument("--force", action="store_true", help="undo even if touched files changed since")
    common(p_undo)
    return parser


def _emit_json(payload: Dict[str, Any]) -> None:
    envelope = {"tool": "linkmend", "version": __version__}
    envelope.update(payload)
    print(json.dumps(envelope, indent=2, sort_keys=True))


def _plan_json(plan: MovePlan) -> Dict[str, Any]:
    return {
        "moves": [{"from": m.src, "to": m.dst} for m in plan.moves],
        "edits": [
            {"path": e.path, "line": e.line, "old": e.old, "new": e.new}
            for e in plan.edits
        ],
        "stats": {
            "files_moved": plan.files_moved,
            "files_edited": plan.files_edited,
            "links_rewritten": plan.links_rewritten,
        },
    }


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _cmd_mv(args: argparse.Namespace) -> int:
    root = Path(args.vault)
    index = build_index(root)
    plan = plan_move(root, index, args.src, args.dst)
    if args.dry_run:
        if args.json:
            _emit_json({"command": "mv", "dry_run": True, **_plan_json(plan)})
        else:
            print(
                f"plan: move {_plural(plan.files_moved, 'file')}, "
                f"rewrite {_plural(plan.links_rewritten, 'link')} in "
                f"{_plural(plan.files_edited, 'file')}  (dry run, nothing written)"
            )
            for m in plan.moves:
                print(f"  {m.src} -> {m.dst}")
            for e in plan.edits:
                print(f"  {e.path}:{e.line}  {e.old.strip()} -> {e.new}")
        return EXIT_OK
    result = apply_plan(root, plan)
    txn = record_transaction(root, plan.command_line(), result)
    if args.json:
        _emit_json({"command": "mv", "dry_run": False, "transaction": txn.id, **_plan_json(plan)})
    else:
        print(
            f"moved {_plural(plan.files_moved, 'file')}, "
            f"rewrote {_plural(plan.links_rewritten, 'link')} in "
            f"{_plural(plan.files_edited, 'file')}  (transaction #{txn.id})"
        )
        for m in plan.moves:
            print(f"  {m.src} -> {m.dst}")
        edited = sorted({e.path for e in plan.edits})
        for path in edited:
            count = sum(1 for e in plan.edits if e.path == path)
            print(f"  {path}: {_plural(count, 'link')} rewritten")
        print(f"undo with: linkmend undo {txn.id}")
    return EXIT_OK


def _cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.vault)
    report = check_vault(root, build_index(root))
    if args.json:
        _emit_json(
            {
                "command": "check",
                "broken": [
                    {
                        "path": b.path,
                        "line": b.line,
                        "link": b.raw,
                        "kind": b.kind,
                        "reason": b.reason,
                        "candidates": list(b.candidates),
                    }
                    for b in report.broken
                ],
                "notes_checked": report.notes_checked,
                "links_checked": report.links_checked,
            }
        )
        return EXIT_FINDINGS if report.broken else EXIT_OK
    if not report.broken:
        print(
            f"no broken links  (checked {_plural(report.links_checked, 'link')} "
            f"in {_plural(report.notes_checked, 'note')})"
        )
        return EXIT_OK
    width = max(len(f"{b.path}:{b.line}") for b in report.broken)
    for b in report.broken:
        where = f"{b.path}:{b.line}"
        detail = "no such target" if b.reason == "missing" else (
            "ambiguous: " + ", ".join(b.candidates)
        )
        shown = f"[[{b.raw}]]" if b.kind == "wiki" else b.raw
        print(f"{where:<{width}}  {shown}  ({detail})")
    print(
        f"{_plural(len(report.broken), 'broken link')} in "
        f"{_plural(report.files_affected, 'note')}  "
        f"(checked {_plural(report.links_checked, 'link')} in {_plural(report.notes_checked, 'note')})"
    )
    return EXIT_FINDINGS


def _cmd_backlinks(args: argparse.Namespace) -> int:
    root = Path(args.vault)
    hits = find_backlinks(root, build_index(root), args.note)
    if args.json:
        _emit_json(
            {
                "command": "backlinks",
                "note": args.note,
                "backlinks": [
                    {"path": h.path, "line": h.line, "link": h.raw, "kind": h.kind}
                    for h in hits
                ],
            }
        )
        return EXIT_OK
    for h in hits:
        shown = f"[[{h.raw}]]" if h.kind == "wiki" else h.raw
        print(f"{h.path}:{h.line}  {shown}")
    files = len({h.path for h in hits})
    print(f"{_plural(len(hits), 'backlink')} from {_plural(files, 'note')}")
    return EXIT_OK


def _cmd_log(args: argparse.Namespace) -> int:
    txns = load_transactions(Path(args.vault))
    txns.reverse()  # newest first, like git log
    if args.limit > 0:
        txns = txns[: args.limit]
    if args.json:
        _emit_json(
            {
                "command": "log",
                "transactions": [
                    {
                        "id": t.id,
                        "created_at": t.created_at,
                        "command": t.command,
                        "stats": t.stats,
                        "undone": t.undone,
                    }
                    for t in txns
                ],
            }
        )
        return EXIT_OK
    if not txns:
        print("journal is empty")
        return EXIT_OK
    for t in txns:
        moved = t.stats.get("files_moved", 0)
        edited = t.stats.get("files_edited", 0)
        state = "  (undone)" if t.undone else ""
        print(
            f"#{t.id}  {t.created_at}  {t.command}  "
            f"[{_plural(moved, 'file')} moved, {_plural(edited, 'note')} rewritten]{state}"
        )
    return EXIT_OK


def _cmd_undo(args: argparse.Namespace) -> int:
    root = Path(args.vault)
    txn = find_transaction(root, args.id)
    if args.dry_run:
        problems = (
            [f"transaction #{txn.id} was already undone at {txn.undone_at}"]
            if txn.undone
            else verify_undo(root, txn)
        )
        if args.json:
            _emit_json(
                {
                    "command": "undo",
                    "dry_run": True,
                    "transaction": txn.id,
                    "would_restore": [e.path for e in txn.edits],
                    "would_move_back": [{"from": d, "to": s} for s, d in txn.moves],
                    "conflicts": problems,
                }
            )
        else:
            print(f"would undo transaction #{txn.id}: {txn.command}")
            for src, dst in txn.moves:
                print(f"  {dst} -> {src}")
            for e in txn.edits:
                print(f"  restore {e.path}")
            for p in problems:
                print(f"  conflict: {p}")
        return EXIT_FINDINGS if problems else EXIT_OK
    txn = undo_transaction(root, txn, force=args.force)
    if args.json:
        _emit_json(
            {
                "command": "undo",
                "dry_run": False,
                "transaction": txn.id,
                "restored": [e.path for e in txn.edits],
                "moved_back": [{"from": d, "to": s} for s, d in txn.moves],
            }
        )
    else:
        print(
            f"undid transaction #{txn.id}: {txn.command}  "
            f"({_plural(len(txn.moves), 'file')} moved back, "
            f"{_plural(len(txn.edits), 'note')} restored)"
        )
    return EXIT_OK


_HANDLERS = {
    "mv": _cmd_mv,
    "check": _cmd_check,
    "backlinks": _cmd_backlinks,
    "log": _cmd_log,
    "undo": _cmd_undo,
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return EXIT_ERROR
    try:
        return _HANDLERS[args.command](args)
    except JournalConflictError as exc:
        print(f"linkmend: refused: {exc}", file=sys.stderr)
        print("linkmend: re-run with --force to undo anyway", file=sys.stderr)
        return EXIT_FINDINGS
    except LinkmendError as exc:
        print(f"linkmend: error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
