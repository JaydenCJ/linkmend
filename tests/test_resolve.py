"""Resolution tests: Markdown path semantics and Obsidian-style wiki names."""

from __future__ import annotations

from linkmend.links import scan_links
from linkmend.resolve import AMBIGUOUS, DIR, FILE, MISSING, resolve_link
from linkmend.vault import build_index


def resolve_in(make_vault, files, source, markdown):
    root = make_vault(files)
    index = build_index(root)
    link = scan_links(markdown)[0]
    return resolve_link(link, source, index)


VAULT = {
    "index.md": "x",
    "notes/api.md": "x",
    "notes/deep/Design.md": "x",
    "notes/my note.md": "x",
    "guides/Setup.md": "x",
    "attic/Setup.md": "x",
    "assets/logo.png": b"png",
}


def test_relative_paths_resolve_from_the_containing_note(make_vault):
    sibling = resolve_in(make_vault, VAULT, "notes/api.md", "[d](deep/Design.md)")
    assert (sibling.status, sibling.path) == (FILE, "notes/deep/Design.md")
    parent = resolve_in(make_vault, VAULT, "notes/api.md", "[i](../index.md)")
    assert (parent.status, parent.path) == (FILE, "index.md")
    encoded = resolve_in(make_vault, VAULT, "index.md", "[m](notes/my%20note.md)")
    assert (encoded.status, encoded.path) == (FILE, "notes/my note.md")


def test_vault_absolute_and_extensionless_paths(make_vault):
    absolute = resolve_in(make_vault, VAULT, "notes/deep/Design.md", "[i](/notes/api.md)")
    assert (absolute.status, absolute.path) == (FILE, "notes/api.md")
    bare = resolve_in(make_vault, VAULT, "index.md", "[a](notes/api)")
    assert bare.status == FILE and bare.path == "notes/api.md" and bare.via_md_ext


def test_directory_escape_and_missing_outcomes(make_vault):
    directory = resolve_in(make_vault, VAULT, "index.md", "[g](guides/)")
    assert (directory.status, directory.path) == (DIR, "guides")
    escape = resolve_in(make_vault, VAULT, "index.md", "[x](../outside.md)")
    assert escape.status == MISSING  # beyond the root: nothing we can mend
    gone = resolve_in(make_vault, VAULT, "index.md", "[x](notes/gone.md)")
    assert gone.status == MISSING


# --- wiki names --------------------------------------------------------------


def test_wiki_bare_unique_stem_found_anywhere_in_vault(make_vault):
    res = resolve_in(make_vault, VAULT, "index.md", "[[Design]]")
    assert (res.status, res.path) == (FILE, "notes/deep/Design.md")


def test_wiki_path_suffix_disambiguates(make_vault):
    res = resolve_in(make_vault, VAULT, "index.md", "[[guides/Setup]]")
    assert (res.status, res.path) == (FILE, "guides/Setup.md")


def test_wiki_duplicate_stem_is_ambiguous_with_sorted_candidates(make_vault):
    res = resolve_in(make_vault, VAULT, "index.md", "[[Setup]]")
    assert res.status == AMBIGUOUS
    assert res.candidates == ("attic/Setup.md", "guides/Setup.md")


def test_wiki_case_insensitive_fallback_but_exact_case_wins(make_vault):
    fallback = resolve_in(make_vault, VAULT, "index.md", "[[design]]")
    assert (fallback.status, fallback.path) == (FILE, "notes/deep/Design.md")
    files = dict(VAULT)
    files["notes/design.md"] = "x"  # lowercase twin of deep/Design.md
    exact = resolve_in(make_vault, files, "index.md", "[[design]]")
    assert (exact.status, exact.path) == (FILE, "notes/design.md")


def test_wiki_non_markdown_needs_extension(make_vault):
    res = resolve_in(make_vault, VAULT, "index.md", "![[logo.png]]")
    assert (res.status, res.path) == (FILE, "assets/logo.png")


def test_wiki_missing_name(make_vault):
    res = resolve_in(make_vault, VAULT, "index.md", "[[Nowhere]]")
    assert res.status == MISSING


def test_wiki_explicit_md_extension_resolves(make_vault):
    res = resolve_in(make_vault, VAULT, "index.md", "[[api.md]]")
    assert (res.status, res.path) == (FILE, "notes/api.md")
