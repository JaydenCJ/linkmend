"""Planner tests: the three link populations, conflicts, and dry safety.

A plan must be pure (no writes) and complete (every affected link, nothing
else). Tests build tiny vaults and assert on the exact edit list.
"""

from __future__ import annotations

import pytest

from linkmend.errors import PlanError, VaultError
from linkmend.plan import plan_move
from linkmend.vault import build_index


def plan(root, src, dst):
    return plan_move(root, build_index(root), src, dst)


def edits_for(p, path):
    return [(e.old, e.new) for e in p.edits if e.path == path]


def test_inbound_links_rewritten_and_counted(make_vault):
    root = make_vault(
        {
            "index.md": "[a](Alpha.md) [[Alpha]]",
            "guide.md": "[a](./Alpha.md)",
            "Alpha.md": "x",
        }
    )
    p = plan(root, "Alpha.md", "Renamed.md")
    assert edits_for(p, "index.md") == [("Alpha.md", "Renamed.md"), ("Alpha", "Renamed")]
    assert edits_for(p, "guide.md") == [("./Alpha.md", "./Renamed.md")]
    assert (p.files_moved, p.links_rewritten, p.files_edited) == (1, 3, 2)


def test_location_independent_links_untouched_when_only_source_moves(make_vault):
    # Bare wiki names and vault-absolute paths do not care where a note
    # lives; a move without rename must not produce noise edits.
    root = make_vault(
        {"index.md": "[[Alpha]]", "Alpha.md": "[i](/index.md)", "other.md": "x"}
    )
    p = plan(root, "Alpha.md", "attic/Alpha.md")
    assert p.edits == []


def test_moved_notes_own_relative_links_rewritten_but_intra_move_links_kept(make_vault):
    root = make_vault(
        {
            "index.md": "x",
            "proj/a.md": "[home](../index.md) [b](b.md)",
            "proj/b.md": "[a](./a.md)",
        }
    )
    p = plan(root, "proj", "attic/deep/proj")
    # Outbound link re-based; the a<->b links move together and stay valid.
    assert edits_for(p, "proj/a.md") == [("../index.md", "../../../index.md")]
    assert edits_for(p, "proj/b.md") == []


def test_directory_move_carries_attachments_and_rewrites_dir_links(make_vault):
    root = make_vault(
        {
            "index.md": "![l](media/logo.png) and [all media](media/)",
            "media/logo.png": b"png",
            "media/readme.md": "x",
        }
    )
    p = plan(root, "media", "assets")
    assert p.mapping["media/logo.png"] == "assets/logo.png"
    assert edits_for(p, "index.md") == [
        ("media/logo.png", "assets/logo.png"),
        ("media/", "assets/"),
    ]


def test_refdef_rewritten_and_anchor_preserved(make_vault):
    root = make_vault(
        {
            "index.md": '[a](notes/api.md#setup)\n\n[api]: notes/api.md "API"\n',
            "notes/api.md": "x",
        }
    )
    p = plan(root, "notes/api.md", "reference/api.md")
    assert edits_for(p, "index.md") == [
        ("notes/api.md#setup", "reference/api.md#setup"),
        ("notes/api.md", "reference/api.md"),
    ]


def test_destination_directory_semantics_match_mv(make_vault):
    root = make_vault(
        {
            "index.md": "[a](Alpha.md)",
            "Alpha.md": "x",
            "attic/keep.md": "x",
            "box/inner.md": "x",
            "shelf/box/old.md": "x",
        }
    )
    # An existing directory destination moves the source *into* it ...
    assert plan(root, "Alpha.md", "attic").mapping == {"Alpha.md": "attic/Alpha.md"}
    # ... a trailing slash forces the same even if the directory is new ...
    assert plan(root, "Alpha.md", "attic2/").mapping == {"Alpha.md": "attic2/Alpha.md"}
    # ... and a directory source nests under an existing directory too.
    assert plan(root, "box", "shelf/box").mapping == {
        "box/inner.md": "shelf/box/box/inner.md"
    }


def test_code_fences_and_broken_links_left_alone(make_vault):
    root = make_vault(
        {
            "index.md": "```\n[a](Alpha.md)\n```\n[gone](nowhere.md) [b](Alpha.md)\n",
            "Alpha.md": "x",
        }
    )
    p = plan(root, "Alpha.md", "Beta.md")
    assert edits_for(p, "index.md") == [("Alpha.md", "Beta.md")]
    assert p.edits[0].line == 4


def test_ambiguous_wiki_link_never_rewritten(make_vault):
    root = make_vault({"index.md": "[[Setup]]", "a/Setup.md": "x", "b/Setup.md": "x"})
    p = plan(root, "a/Setup.md", "c/Setup.md")
    assert p.edits == []  # rewriting a guess could silently flip the target


def test_wiki_rename_into_collision_widens_to_path(make_vault):
    root = make_vault({"index.md": "[[Alpha]]", "Alpha.md": "x", "attic/Beta.md": "y"})
    p = plan(root, "Alpha.md", "docs/Beta.md")
    assert edits_for(p, "index.md") == [("Alpha", "docs/Beta")]


# --- conflicts and refusals --------------------------------------------------


def test_missing_source_and_occupied_destination_are_plan_errors(make_vault):
    root = make_vault({"a.md": "x", "b.md": "y"})
    with pytest.raises(PlanError, match="source not found"):
        plan(root, "gone.md", "elsewhere.md")
    with pytest.raises(PlanError, match="destination already exists"):
        plan(root, "a.md", "b.md")


def test_degenerate_moves_refused(make_vault):
    root = make_vault({"a.md": "x", "proj/a.md": "x"})
    with pytest.raises(PlanError, match="the same"):
        plan(root, "a.md", "./a.md")
    with pytest.raises(PlanError, match="into itself"):
        plan(root, "proj", "proj/sub")


def test_destination_outside_vault_refused(make_vault):
    root = make_vault({"a.md": "x"})
    with pytest.raises(VaultError, match="escapes the vault"):
        plan(root, "a.md", "../outside.md")


def test_destination_in_hidden_directory_refused(make_vault):
    # Hidden trees are invisible to the index; links into them could never
    # be checked or mended again.
    root = make_vault({"a.md": "x"})
    with pytest.raises(PlanError, match="hidden"):
        plan(root, "a.md", ".secret/a.md")


def test_directory_move_collision_with_existing_file(make_vault):
    # `mv proj attic` nests proj under attic (Unix semantics), where
    # attic/proj/a.md already exists — that must be refused, not clobbered.
    root = make_vault({"proj/a.md": "x", "attic/proj/a.md": "y", "index.md": "z"})
    with pytest.raises(PlanError, match="destination already exists"):
        plan(root, "proj", "attic")
