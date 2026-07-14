"""Scanner tests: every link syntax, span exactness, and code masking.

Span exactness is the load-bearing property — a wrong span would corrupt a
note on rewrite — so tests assert ``text[span] == raw`` alongside the
semantic fields.
"""

from __future__ import annotations

from linkmend.links import ANCHOR, EXTERNAL, INTERNAL, scan_links


def only(text):
    links = scan_links(text)
    assert len(links) == 1, f"expected exactly one link, got {links!r}"
    return links[0]


# --- Markdown inline links -------------------------------------------------


def test_inline_links_images_and_titles():
    text = "See [notes](notes/api.md) and ![logo](assets/logo.png)."
    a, b = scan_links(text)
    assert (a.kind, a.target, a.anchor) == ("inline", "notes/api.md", "")
    assert not a.angle and not a.encoded
    assert a.classification == INTERNAL
    assert b.target == "assets/logo.png"  # images scan exactly like links
    # Titles stay outside the span in both quoting styles.
    titled = '[a](notes/api.md "The API")'
    link = only(titled)
    assert titled[link.span[0] : link.span[1]] == "notes/api.md"
    assert only("[a](x.md 'single quotes')").target == "x.md"


def test_angle_bracket_destination_spans_include_brackets():
    text = "[a](<my note.md>)"
    link = only(text)
    assert link.angle
    assert link.raw == "<my note.md>"
    assert link.target == "my note.md"


def test_percent_encoding_and_backslash_escapes_decode():
    encoded = only("[a](my%20note.md)")
    assert encoded.encoded and encoded.target == "my note.md"
    escaped = only(r"[a](my\ note.md)")
    assert escaped.target == "my note.md" and not escaped.encoded


def test_anchor_split_and_anchor_only_classification():
    with_anchor = only("[a](notes/api.md#setup)")
    assert (with_anchor.target, with_anchor.anchor) == ("notes/api.md", "#setup")
    bare = only("[a](#setup)")
    assert bare.target == "" and bare.classification == ANCHOR


def test_external_schemes_classified_external():
    text = "[a](https://example.test/x) [b](mailto:hi@example.test) [c](//example.test/y)"
    links = scan_links(text)
    assert [l.classification for l in links] == [EXTERNAL, EXTERNAL, EXTERNAL]


def test_balanced_parens_and_multiple_links_keep_exact_spans():
    parens = only("[a](notes/plan(v2).md)")
    assert parens.target == "notes/plan(v2).md"
    assert parens.raw == "notes/plan(v2).md"
    text = "[a](one.md) and [b](two.md)"
    links = scan_links(text)
    for link in links:
        assert text[link.span[0] : link.span[1]] == link.raw
    assert [l.target for l in links] == ["one.md", "two.md"]


def test_malformed_destinations_are_not_links():
    assert scan_links("[a](broken.md and text") == []  # unclosed paren
    assert scan_links("[a]()") == []  # empty destination


# --- Reference definitions ---------------------------------------------------


def test_reference_definition_destination_found_plain_and_angled():
    plain = only('[api]: notes/api.md "The API"\n')
    assert plain.kind == "refdef"
    assert plain.target == "notes/api.md"
    angled = only("[api]: <my notes.md>\n")
    assert angled.angle and angled.target == "my notes.md"


def test_refdef_lookalikes_are_not_definitions():
    # CommonMark: 4+ leading spaces makes an indented code block ...
    assert all(l.kind != "refdef" for l in scan_links("    [api]: notes/api.md\n"))
    # ... and a [text][label] usage carries no path; only its definition does.
    text = "See [the api][api].\n\n[api]: notes/api.md\n"
    links = scan_links(text)
    assert len(links) == 1 and links[0].kind == "refdef"


# --- Wiki links --------------------------------------------------------------


def test_wiki_link_basic_and_embed():
    link = only("See [[My Note]].")
    assert (link.kind, link.target, link.anchor) == ("wiki", "My Note", "")
    assert link.classification == INTERNAL
    assert only("![[diagram.png]]").target == "diagram.png"


def test_wiki_anchor_and_alias_stay_outside_the_span():
    text = "[[My Note#Heading|alias]]"
    link = only(text)
    assert text[link.span[0] : link.span[1]] == "My Note"
    assert (link.target, link.anchor) == ("My Note", "#Heading")


def test_wiki_whitespace_trimming_and_anchor_only_form():
    padded = only("[[ My Note ]]")
    assert padded.raw == " My Note "
    assert padded.target == "My Note"
    self_ref = only("[[#Heading]]")
    assert self_ref.target == "" and self_ref.classification == ANCHOR


# --- Code masking ------------------------------------------------------------


def test_links_inside_fences_ignored_for_both_markers():
    backtick = "```\n[a](x.md)\n[[Wiki]]\n```\n[b](real.md)\n"
    assert [l.target for l in scan_links(backtick)] == ["real.md"]
    tilde = "~~~text\n[a](x.md)\n~~~\n"
    assert scan_links(tilde) == []


def test_fence_length_rules_and_unclosed_fence():
    # A ```` fence is only closed by a marker at least as long.
    nested = "````\n```\n[a](x.md)\n````\n[b](real.md)\n"
    assert [l.target for l in scan_links(nested)] == ["real.md"]
    # An unclosed fence masks to end of file.
    assert scan_links("```\n[a](x.md)\n[[Wiki]]\n") == []


def test_inline_code_spans_mask_links_but_stray_backticks_do_not():
    single = "run `linkmend mv [a](x.md)` then see [b](real.md)"
    assert [l.target for l in scan_links(single)] == ["real.md"]
    double = "``code with ` [a](x.md) ``  [b](real.md)"
    assert [l.target for l in scan_links(double)] == ["real.md"]
    stray = "a stray ` backtick, then [b](real.md)"
    assert [l.target for l in scan_links(stray)] == ["real.md"]


# --- Line numbers ------------------------------------------------------------


def test_line_numbers_are_one_based_and_correct():
    text = "first\n\n[a](one.md)\ntext [[Two]]\n"
    links = scan_links(text)
    assert [(l.target, l.line) for l in links] == [("one.md", 3), ("Two", 4)]
