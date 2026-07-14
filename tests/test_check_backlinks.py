"""Diagnostics tests: broken-link detection and backlink listing."""

from __future__ import annotations

from linkmend.check import check_vault, find_backlinks
from linkmend.vault import build_index


def check(root):
    return check_vault(root, build_index(root))


def test_clean_vault_reports_nothing(make_vault):
    root = make_vault({"index.md": "[a](a.md) [[a]]", "a.md": "x"})
    report = check(root)
    assert report.broken == ()
    assert report.links_checked == 2
    assert report.notes_checked == 2


def test_missing_targets_reported_with_location_for_both_syntaxes(make_vault):
    root = make_vault({"index.md": "line one\n[bad](gone.md)\n[[Nowhere]]\n"})
    md, wiki = check(root).broken
    assert (md.path, md.line, md.raw, md.reason) == ("index.md", 2, "gone.md", "missing")
    assert (wiki.kind, wiki.line, wiki.reason) == ("wiki", 3, "missing")


def test_ambiguous_wiki_link_reported_with_candidates(make_vault):
    root = make_vault({"index.md": "[[Setup]]", "a/Setup.md": "x", "b/Setup.md": "y"})
    (broken,) = check(root).broken
    assert broken.reason == "ambiguous"
    assert broken.candidates == ("a/Setup.md", "b/Setup.md")


def test_external_and_anchor_links_not_counted_or_flagged(make_vault):
    root = make_vault({"index.md": "[e](https://example.test) [s](#top)"})
    report = check(root)
    assert report.broken == () and report.links_checked == 0


def test_broken_link_inside_code_fence_ignored(make_vault):
    root = make_vault({"index.md": "```\n[bad](gone.md)\n```\n"})
    assert check(root).broken == ()


def test_backlinks_finds_markdown_wiki_and_refdef_forms(make_vault):
    root = make_vault(
        {
            "index.md": "[a](notes/api.md)\n[[api]]\n\n[ref]: notes/api.md\n",
            "guide.md": "[deep](./notes/api.md#setup)\n",
            "notes/api.md": "x",
        }
    )
    hits = find_backlinks(root, build_index(root), "notes/api.md")
    assert [(h.path, h.line, h.kind) for h in hits] == [
        ("guide.md", 1, "inline"),
        ("index.md", 1, "inline"),
        ("index.md", 2, "wiki"),
        ("index.md", 4, "refdef"),
    ]


def test_backlinks_extensionless_argument_and_unlinked_note(make_vault):
    root = make_vault({"index.md": "[[api]]", "notes/api.md": "x", "lonely.md": "y"})
    assert len(find_backlinks(root, build_index(root), "notes/api")) == 1
    assert find_backlinks(root, build_index(root), "lonely.md") == []
