"""Undo tests: byte-exact reversal, drift refusal, and journal state.

The promise on the box: ``undo`` restores the vault to the exact pre-move
state — same paths, same bytes — unless something else touched the files,
in which case it refuses with a per-file conflict list.
"""

from __future__ import annotations

import pytest

from linkmend.apply import apply_plan
from linkmend.errors import JournalConflictError, JournalError
from linkmend.journal import (
    find_transaction,
    load_transactions,
    record_transaction,
    undo_transaction,
    verify_undo,
)
from linkmend.plan import plan_move
from linkmend.vault import build_index


def do_move(root, src, dst):
    p = plan_move(root, build_index(root), src, dst)
    return record_transaction(root, p.command_line(), apply_plan(root, p))


def snapshot(root):
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".linkmend" not in p.parts
    }


def test_undo_restores_vault_byte_for_byte_and_prunes_new_dirs(make_vault):
    root = make_vault(
        {
            "index.md": "[a](proj/a.md) and [[b]]\n",
            "proj/a.md": "[home](../index.md)\n",
            "proj/b.md": "note b\n",
        }
    )
    before = snapshot(root)
    txn = do_move(root, "proj", "archive/deep/proj")
    assert snapshot(root) != before  # the move really happened
    undo_transaction(root, txn)
    assert snapshot(root) == before
    assert not (root / "archive").exists()  # directories the move created


def test_undo_marks_transaction_undone_in_the_journal(make_vault):
    root = make_vault({"a.md": "x", "index.md": "[a](a.md)"})
    txn = do_move(root, "a.md", "b.md")
    undo_transaction(root, txn)
    (loaded,) = load_transactions(root)
    assert loaded.undone and loaded.undone_at


def test_undo_picks_newest_active_transaction_by_default(make_vault):
    root = make_vault({"a.md": "x", "b.md": "y", "index.md": "[a](a.md) [b](b.md)"})
    do_move(root, "a.md", "a2.md")
    do_move(root, "b.md", "b2.md")
    undo_transaction(root, find_transaction(root, None))
    assert (root / "b.md").exists()  # #2 reversed
    assert (root / "a2.md").exists()  # #1 still applied
    undo_transaction(root, find_transaction(root, None))
    assert (root / "a.md").exists()


def test_undo_specific_transaction_by_id(make_vault):
    root = make_vault({"a.md": "x", "index.md": "[a](a.md)"})
    txn = do_move(root, "a.md", "b.md")
    undo_transaction(root, find_transaction(root, txn.id))
    assert (root / "a.md").exists()


def test_bad_undo_requests_are_journal_errors(make_vault):
    root = make_vault({"a.md": "x"})
    with pytest.raises(JournalError, match="nothing to undo"):
        find_transaction(root, None)
    with pytest.raises(JournalError, match="no transaction #7"):
        find_transaction(root, 7)


def test_undo_refuses_when_rewritten_note_changed_since(make_vault):
    root = make_vault({"index.md": "[a](a.md)", "a.md": "x"})
    txn = do_move(root, "a.md", "b.md")
    (root / "index.md").write_text("hand-edited after the move", encoding="utf-8")
    with pytest.raises(JournalConflictError, match="index.md"):
        undo_transaction(root, txn)
    # The refusal must leave the drifted file untouched.
    assert (root / "index.md").read_text(encoding="utf-8") == "hand-edited after the move"


def test_verify_reports_missing_moved_file_and_reoccupied_source(make_vault):
    root = make_vault({"index.md": "[a](a.md)", "a.md": "x"})
    txn = do_move(root, "a.md", "b.md")
    (root / "b.md").rename(root / "elsewhere.md")
    problems = verify_undo(root, txn)
    assert any("b.md" in p and "gone" in p for p in problems)
    (root / "a.md").write_text("squatter", encoding="utf-8")
    problems = verify_undo(root, txn)
    assert any("a.md" in p and "occupied" in p for p in problems)
    # Repair both paths, then tamper with the moved file's *content*: the
    # per-move fingerprint must flag it even though b.md was never rewritten
    # (only index.md was), so the edits[] hashes alone would miss this.
    (root / "a.md").unlink()
    (root / "elsewhere.md").rename(root / "b.md")
    (root / "b.md").write_text("edited after the move", encoding="utf-8")
    problems = verify_undo(root, txn)
    assert any("b.md" in p and "modified" in p for p in problems)
    with pytest.raises(JournalConflictError, match="b.md"):
        undo_transaction(root, txn)


def test_force_overrides_drift_and_restores_preimage(make_vault):
    root = make_vault({"index.md": "[a](a.md)", "a.md": "x"})
    txn = do_move(root, "a.md", "b.md")
    (root / "index.md").write_text("hand-edited", encoding="utf-8")
    undo_transaction(root, txn, force=True)
    assert (root / "index.md").read_text(encoding="utf-8") == "[a](a.md)"
    assert (root / "a.md").exists()


def test_double_undo_is_refused_even_with_force(make_vault):
    root = make_vault({"index.md": "[a](a.md)", "a.md": "x"})
    txn = do_move(root, "a.md", "b.md")
    undo_transaction(root, txn)
    fresh = find_transaction(root, txn.id)
    with pytest.raises(JournalError, match="already undone"):
        undo_transaction(root, fresh, force=True)


def test_move_again_after_undo_appends_a_new_transaction(make_vault):
    root = make_vault({"index.md": "[a](a.md)", "a.md": "x"})
    txn = do_move(root, "a.md", "b.md")
    undo_transaction(root, txn)
    txn2 = do_move(root, "a.md", "c.md")
    assert txn2.id == 2
    assert (root / "index.md").read_text(encoding="utf-8") == "[a](c.md)"
