"""Rewrite tests: style preservation is the contract.

Each test feeds a parsed link plus post-move locations into the rewriter
and asserts on the exact replacement text — relative vs absolute, ``./``
prefixes, encodings, angle brackets, extensions, and wiki-name width.
"""

from __future__ import annotations

from linkmend.links import scan_links
from linkmend.resolve import Resolution
from linkmend.rewrite import rewrite_md_destination, rewrite_wiki_target


def link_from(markdown):
    return scan_links(markdown)[0]


def res(via_md_ext=False):
    return Resolution("file", path="ignored", via_md_ext=via_md_ext)


def test_relative_paths_recomputed_from_new_locations():
    rename = rewrite_md_destination(
        link_from("[a](Alpha.md)"), "notes/index.md", "notes/Beta.md", res()
    )
    assert rename == "Beta.md"
    across = rewrite_md_destination(
        link_from("[a](Alpha.md)"), "index.md", "archive/2026/Alpha.md", res()
    )
    assert across == "archive/2026/Alpha.md"
    upward = rewrite_md_destination(
        link_from("[a](../index.md)"), "attic/deep/Note.md", "index.md", res()
    )
    assert upward == "../../index.md"


def test_dot_slash_prefix_preserved():
    out = rewrite_md_destination(link_from("[a](./Alpha.md)"), "index.md", "Beta.md", res())
    assert out == "./Beta.md"


def test_vault_absolute_style_preserved():
    out = rewrite_md_destination(
        link_from("[a](/notes/Alpha.md)"), "anywhere/x.md", "attic/Alpha.md", res()
    )
    assert out == "/attic/Alpha.md"


def test_space_in_new_path_switches_to_angle_brackets():
    out = rewrite_md_destination(
        link_from("[a](Alpha.md)"), "index.md", "My Notes/Alpha.md", res()
    )
    assert out == "<My Notes/Alpha.md>"


def test_encoded_style_stays_encoded_never_angled():
    spaced = rewrite_md_destination(
        link_from("[a](My%20Note.md)"), "index.md", "attic/My Note.md", res()
    )
    assert spaced == "attic/My%20Note.md"
    parens = rewrite_md_destination(
        link_from("[a](Alpha%20v1.md)"), "index.md", "Alpha (final).md", res()
    )
    assert parens == "Alpha%20%28final%29.md"


def test_angle_style_preserved_even_without_spaces():
    out = rewrite_md_destination(link_from("[a](<Alpha.md>)"), "index.md", "Beta.md", res())
    assert out == "<Beta.md>"


def test_extensionless_style_preserved():
    out = rewrite_md_destination(
        link_from("[a](notes/api)"), "index.md", "reference/api.md", res(via_md_ext=True)
    )
    assert out == "reference/api"


def test_anchor_survives_rewrite():
    out = rewrite_md_destination(link_from("[a](Alpha.md#setup)"), "index.md", "Beta.md", res())
    assert out == "Beta.md#setup"


def test_directory_link_keeps_trailing_slash():
    out = rewrite_md_destination(
        link_from("[g](guides/)"), "index.md", "handbook", Resolution("dir", path="guides")
    )
    assert out == "handbook/"


# --- wiki targets ------------------------------------------------------------


def test_wiki_bare_name_stays_bare_until_a_collision_forces_a_path():
    unique = rewrite_wiki_target(link_from("[[Alpha]]"), "archive/Beta.md", {"beta": 1})
    assert unique == "Beta"
    collision = rewrite_wiki_target(link_from("[[Alpha]]"), "archive/Beta.md", {"beta": 2})
    assert collision == "archive/Beta"


def test_wiki_path_style_stays_path_style():
    out = rewrite_wiki_target(link_from("[[notes/Alpha]]"), "archive/Alpha.md", {"alpha": 1})
    assert out == "archive/Alpha"


def test_wiki_extension_styles_preserved():
    explicit = rewrite_wiki_target(link_from("[[Alpha.md]]"), "Beta.md", {"beta": 1})
    assert explicit == "Beta.md"
    attachment = rewrite_wiki_target(link_from("![[logo.png]]"), "img/brand.png", {"brand.png": 1})
    assert attachment == "brand.png"
