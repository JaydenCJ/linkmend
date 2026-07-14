"""The undo journal: every ``mv`` is a numbered, reversible transaction.

Each transaction is one JSON file under ``.linkmend/journal/`` inside the
vault, recording the file moves and the byte-exact pre-image of every note
that was rewritten, plus SHA-256 fingerprints of the before and after
states. ``undo`` verifies those fingerprints first: if any touched file
changed since the transaction, the undo is refused (``--force`` overrides,
per-file conflicts listed) — linkmend never silently destroys later edits.

The journal is plain JSON on purpose: human-inspectable, greppable, and
trivially safe to delete once you trust a reorganization.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .apply import ApplyResult
from .errors import JournalConflictError, JournalError
from .vault import sha256_bytes, write_note

JOURNAL_DIR = ".linkmend/journal"
JOURNAL_VERSION = 1


@dataclass(frozen=True)
class EditRecord:
    """One rewritten note: where it lives now, and how to restore it."""

    path: str  # post-move location
    before_sha256: str
    after_sha256: str
    encoding: str  # "utf-8" | "base64"
    before: str  # pre-image payload in the encoding above

    def before_bytes(self) -> bytes:
        if self.encoding == "base64":
            return base64.b64decode(self.before)
        return self.before.encode("utf-8")


@dataclass
class Transaction:
    id: int
    created_at: str
    command: str
    moves: List[Tuple[str, str]]  # (src, dst)
    edits: List[EditRecord]
    undone: bool = False
    undone_at: str = ""
    stats: Dict[str, int] = field(default_factory=dict)
    move_sha256: Dict[str, str] = field(default_factory=dict)  # dst -> post-move sha256

    def to_json(self) -> Dict:
        return {
            "journal_version": JOURNAL_VERSION,
            "id": self.id,
            "created_at": self.created_at,
            "command": self.command,
            "moves": [
                {"from": s, "to": d, "sha256": self.move_sha256.get(d, "")}
                for s, d in self.moves
            ],
            "edits": [
                {
                    "path": e.path,
                    "before_sha256": e.before_sha256,
                    "after_sha256": e.after_sha256,
                    "encoding": e.encoding,
                    "before": e.before,
                }
                for e in self.edits
            ],
            "undone": self.undone,
            "undone_at": self.undone_at,
            "stats": self.stats,
        }

    @staticmethod
    def from_json(data: Dict) -> "Transaction":
        try:
            return Transaction(
                id=int(data["id"]),
                created_at=str(data["created_at"]),
                command=str(data["command"]),
                moves=[(m["from"], m["to"]) for m in data["moves"]],
                edits=[
                    EditRecord(
                        path=e["path"],
                        before_sha256=e["before_sha256"],
                        after_sha256=e["after_sha256"],
                        encoding=e["encoding"],
                        before=e["before"],
                    )
                    for e in data["edits"]
                ],
                undone=bool(data.get("undone", False)),
                undone_at=str(data.get("undone_at", "")),
                stats=dict(data.get("stats", {})),
                # Absent in journals written before the per-move fingerprint
                # existed; verification simply skips moves without one.
                move_sha256={
                    m["to"]: m["sha256"] for m in data["moves"] if m.get("sha256")
                },
            )
        except (KeyError, TypeError) as exc:
            raise JournalError(f"corrupt journal entry: missing {exc}") from exc


def _journal_dir(root: Path) -> Path:
    return Path(root) / JOURNAL_DIR


def _txn_path(root: Path, txn_id: int) -> Path:
    return _journal_dir(root) / f"{txn_id:04d}.json"


def _write_txn(root: Path, txn: Transaction) -> None:
    path = _txn_path(root, txn.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(txn.to_json(), indent=2, sort_keys=True, ensure_ascii=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(payload + "\n", encoding="ascii")
    tmp.replace(path)


def load_transactions(root: Path) -> List[Transaction]:
    """All transactions, oldest first. An empty/absent journal is fine."""
    jdir = _journal_dir(root)
    if not jdir.is_dir():
        return []
    txns = []
    for entry in sorted(jdir.glob("[0-9][0-9][0-9][0-9].json")):
        try:
            txns.append(Transaction.from_json(json.loads(entry.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, OSError) as exc:
            raise JournalError(f"corrupt journal entry {entry.name}: {exc}") from exc
    txns.sort(key=lambda t: t.id)
    return txns


def next_id(root: Path) -> int:
    txns = load_transactions(root)
    return (txns[-1].id + 1) if txns else 1


def record_transaction(root: Path, command: str, result: ApplyResult) -> Transaction:
    """Persist one applied move as the newest journal entry."""
    edits = []
    for e in result.edits:
        try:
            payload, encoding = e.before.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            payload, encoding = base64.b64encode(e.before).decode("ascii"), "base64"
        edits.append(
            EditRecord(
                path=e.path,
                before_sha256=e.before_sha256,
                after_sha256=e.after_sha256,
                encoding=encoding,
                before=payload,
            )
        )
    txn = Transaction(
        id=next_id(root),
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        command=command,
        moves=list(result.moves),
        edits=edits,
        stats={
            "files_moved": len(result.moves),
            "files_edited": len(result.edits),
        },
        move_sha256=dict(result.move_sha256),
    )
    _write_txn(root, txn)
    return txn


def find_transaction(root: Path, txn_id: Optional[int]) -> Transaction:
    """The transaction to undo: an explicit id, or the newest active one."""
    txns = load_transactions(root)
    if txn_id is not None:
        for t in txns:
            if t.id == txn_id:
                return t
        raise JournalError(f"no transaction #{txn_id} in the journal")
    active = [t for t in txns if not t.undone]
    if not active:
        raise JournalError("nothing to undo: the journal has no active transactions")
    return active[-1]


def verify_undo(root: Path, txn: Transaction) -> List[str]:
    """Check the vault still matches the transaction's after-state."""
    problems = []
    root = Path(root)
    for edit in txn.edits:
        target = root / edit.path
        if not target.is_file():
            problems.append(f"{edit.path}: rewritten note is gone")
            continue
        if sha256_bytes(target.read_bytes()) != edit.after_sha256:
            problems.append(f"{edit.path}: modified after this transaction")
    edited = {e.path for e in txn.edits}
    for src, dst in txn.moves:
        if dst not in edited:
            target = root / dst
            if not target.is_file():
                problems.append(f"{dst}: moved file is gone")
            else:
                # Rewritten notes were hashed above; purely-moved files carry
                # their own fingerprint so post-move edits are caught too.
                expected = txn.move_sha256.get(dst, "")
                if expected and sha256_bytes(target.read_bytes()) != expected:
                    problems.append(f"{dst}: modified after this transaction")
        if (root / src).exists():
            problems.append(f"{src}: original path is occupied again")
    return problems


def undo_transaction(root: Path, txn: Transaction, force: bool = False) -> Transaction:
    """Reverse ``txn``: restore pre-images, move files back, mark undone."""
    if txn.undone:
        # Not forceable on purpose: re-running a finished undo could resurrect
        # files the user has since deleted.
        raise JournalError(f"transaction #{txn.id} was already undone at {txn.undone_at}")
    problems = verify_undo(root, txn)
    if problems and not force:
        raise JournalConflictError(problems)
    root = Path(root)
    # Restore rewritten notes first (still at their post-move locations) ...
    for edit in txn.edits:
        write_note(root, edit.path, edit.before_bytes())
    # ... then walk the moves backwards so files carry the restored content.
    for src, dst in reversed(txn.moves):
        dst_abs = root / dst
        src_abs = root / src
        if not dst_abs.exists():
            continue  # verified above unless --force; skip what vanished
        src_abs.parent.mkdir(parents=True, exist_ok=True)
        dst_abs.replace(src_abs)
    # Prune directories the move created, walking each one up toward the root.
    for _src, dst in txn.moves:
        parent = (root / dst).parent
        while parent != root:
            try:
                parent.rmdir()
            except OSError:
                break  # not empty: everything above it is not empty either
            parent = parent.parent
    txn.undone = True
    txn.undone_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_txn(root, txn)
    return txn
