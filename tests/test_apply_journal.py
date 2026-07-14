"""Apply + journal tests: disk effects, atomicity guards, and the record.

The invariant under test: after ``apply_plan`` + ``record_transaction`` the
vault has zero broken links, and the journal entry alone is enough to
reconstruct the exact pre-move bytes of every touched file.
"""

from __future__ import annotations

import json

import pytest

from linkmend.apply import apply_plan
from linkmend.check import check_vault
from linkmend.errors import PlanError
from linkmend.journal import load_transactions, record_transaction
from linkmend.plan import plan_move
from linkmend.vault import build_index, sha256_bytes


def do_move(root, src, dst):
    index = build_index(root)
    p = plan_move(root, index, src, dst)
    result = apply_plan(root, p)
    return p, record_transaction(root, p.command_line(), result)


def test_apply_moves_file_and_rewrites_inbound_links(make_vault):
    root = make_vault({"index.md": "see [a](Alpha.md)", "Alpha.md": "body"})
    do_move(root, "Alpha.md", "attic/Alpha.md")
    assert not (root / "Alpha.md").exists()
    assert (root / "attic/Alpha.md").read_text(encoding="utf-8") == "body"
    assert (root / "index.md").read_text(encoding="utf-8") == "see [a](attic/Alpha.md)"


def test_vault_is_link_clean_after_directory_reorganization(make_vault):
    root = make_vault(
        {
            "index.md": "[a](proj/a.md) [[b]] ![i](proj/img.png)\n",
            "proj/a.md": "[home](../index.md) [b](b.md)\n",
            "proj/b.md": "[[a]]\n",
            "proj/img.png": b"png",
        }
    )
    do_move(root, "proj", "archive/2026/proj")
    report = check_vault(root, build_index(root))
    assert report.broken == ()


def test_empty_source_directories_pruned_after_dir_move(make_vault):
    root = make_vault({"proj/deep/a.md": "x", "index.md": "[a](proj/deep/a.md)"})
    do_move(root, "proj", "attic")
    assert not (root / "proj").exists()


def test_edited_and_moved_note_gets_content_at_new_location(make_vault):
    root = make_vault({"index.md": "x", "notes/a.md": "[i](../index.md)"})
    do_move(root, "notes/a.md", "deep/down/a.md")
    assert (root / "deep/down/a.md").read_text(encoding="utf-8") == "[i](../../index.md)"


def test_apply_refuses_if_note_changed_between_plan_and_apply(make_vault):
    root = make_vault({"index.md": "[a](Alpha.md)", "Alpha.md": "x"})
    index = build_index(root)
    p = plan_move(root, index, "Alpha.md", "Beta.md")
    (root / "index.md").write_text("EDITED [a](Alpha.md)", encoding="utf-8")
    with pytest.raises(PlanError, match="changed between planning and apply"):
        apply_plan(root, p)
    # Nothing was modified: the move itself must not have happened either.
    assert (root / "Alpha.md").exists()


def test_journal_ids_increment_and_the_journal_stays_out_of_the_index(make_vault):
    root = make_vault({"index.md": "[a](a.md) [b](b.md)", "a.md": "x", "b.md": "y"})
    _, t1 = do_move(root, "a.md", "a2.md")
    _, t2 = do_move(root, "b.md", "b2.md")
    assert (t1.id, t2.id) == (1, 2)
    assert [t.id for t in load_transactions(root)] == [1, 2]
    index = build_index(root)
    assert all(not f.startswith(".linkmend") for f in index.files)


def test_journal_records_byte_exact_preimage_and_hashes(make_vault):
    before = "see [a](Alpha.md) éü\n"
    root = make_vault({"index.md": before, "Alpha.md": "x"})
    do_move(root, "Alpha.md", "Beta.md")
    (txn,) = load_transactions(root)
    (edit,) = txn.edits
    assert edit.path == "index.md"
    assert edit.before_bytes().decode("utf-8") == before
    assert edit.before_sha256 == sha256_bytes(before.encode("utf-8"))
    assert edit.after_sha256 == sha256_bytes((root / "index.md").read_bytes())


def test_journal_file_is_plain_inspectable_json(make_vault):
    root = make_vault({"index.md": "[a](Alpha.md)", "Alpha.md": "x"})
    do_move(root, "Alpha.md", "Beta.md")
    payload = json.loads((root / ".linkmend/journal/0001.json").read_text(encoding="utf-8"))
    assert payload["command"] == "mv Alpha.md Beta.md"
    (move,) = payload["moves"]
    assert move["from"] == "Alpha.md" and move["to"] == "Beta.md"
    # The per-move fingerprint covers files that were moved but not rewritten.
    assert move["sha256"] == sha256_bytes((root / "Beta.md").read_bytes())
    assert payload["journal_version"] == 1
    assert payload["undone"] is False


def test_non_utf8_note_round_trips_through_journal(make_vault):
    raw = b"[a](Alpha.md) \xff\xfe latin\n"
    root = make_vault({"index.md": raw, "Alpha.md": "x"})
    do_move(root, "Alpha.md", "Beta.md")
    (txn,) = load_transactions(root)
    (edit,) = txn.edits
    assert edit.encoding == "base64"
    assert edit.before_bytes() == raw
    assert (root / "index.md").read_bytes() == b"[a](Beta.md) \xff\xfe latin\n"
