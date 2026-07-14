"""End-to-end CLI tests: real argv, real vaults, asserted exit codes.

These run the same ``main()`` the ``linkmend`` console script calls, so
they cover argument parsing, output formatting, JSON envelopes, and the
0/1/2 exit-code contract.
"""

from __future__ import annotations

import json

import pytest

from linkmend import __version__


def write_vault(make_vault):
    return make_vault(
        {
            "index.md": "- [Alpha](Projects/Alpha.md)\n- [[Alpha]]\n",
            "Projects/Alpha.md": "[home](../index.md)\n",
            "Projects/Beta.md": "[a](Alpha.md)\n",
        }
    )


def test_version_flag_and_bare_invocation(run_cli, capsys):
    with pytest.raises(SystemExit) as exc:  # argparse exits 0 on --version
        run_cli("--version")
    assert exc.value.code == 0
    assert f"linkmend {__version__}" in capsys.readouterr().out
    code, out, _err = run_cli()
    assert code == 2 and "usage: linkmend" in out


def test_mv_happy_path_reports_and_moves(run_cli, make_vault):
    root = write_vault(make_vault)
    code, out, err = run_cli("mv", "Projects/Alpha.md", "Archive/Alpha.md", "--vault", str(root))
    assert code == 0 and err == ""
    assert "moved 1 file" in out
    assert "transaction #1" in out
    assert (root / "Archive/Alpha.md").exists()


def test_mv_dry_run_prints_plan_but_changes_nothing(run_cli, make_vault):
    root = write_vault(make_vault)
    code, out, _err = run_cli(
        "mv", "Projects/Alpha.md", "Archive/Alpha.md", "--dry-run", "--vault", str(root)
    )
    assert code == 0
    assert "dry run, nothing written" in out
    assert "Projects/Alpha.md -> Archive/Alpha.md" in out
    assert (root / "Projects/Alpha.md").exists()
    assert not (root / "Archive").exists()
    assert not (root / ".linkmend").exists()  # no journal entry either


def test_mv_json_envelope_is_stable(run_cli, make_vault):
    root = write_vault(make_vault)
    code, out, _err = run_cli(
        "mv", "Projects/Alpha.md", "Archive/Alpha.md", "--json", "--vault", str(root)
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["tool"] == "linkmend"
    assert payload["version"] == __version__
    assert payload["command"] == "mv"
    assert payload["transaction"] == 1
    assert payload["stats"]["files_moved"] == 1
    assert {"from": "Projects/Alpha.md", "to": "Archive/Alpha.md"} in payload["moves"]


def test_mv_error_exits_2_with_one_stderr_line(run_cli, make_vault):
    root = write_vault(make_vault)
    code, out, err = run_cli("mv", "missing.md", "x.md", "--vault", str(root))
    assert code == 2 and out == ""
    assert err.startswith("linkmend: error:") and "missing.md" in err


def test_check_exit_codes_and_human_report(run_cli, make_vault):
    clean = write_vault(make_vault)
    code, out, _err = run_cli("check", "--vault", str(clean))
    assert code == 0 and "no broken links" in out
    broken = make_vault({"broken.md": "[bad](gone.md)\n[[Nope]]\n"})
    code, out, _err = run_cli("check", "--vault", str(broken))
    assert code == 1
    assert "broken.md:1" in out and "gone.md" in out
    assert "broken.md:2" in out and "[[Nope]]" in out
    assert "2 broken links in 1 note" in out


def test_check_json_lists_broken_links(run_cli, make_vault):
    root = make_vault({"index.md": "[bad](gone.md)\n"})
    code, out, _err = run_cli("check", "--json", "--vault", str(root))
    assert code == 1
    payload = json.loads(out)
    assert payload["broken"][0]["path"] == "index.md"
    assert payload["broken"][0]["reason"] == "missing"


def test_backlinks_lists_wiki_and_markdown_hits(run_cli, make_vault):
    root = write_vault(make_vault)
    code, out, _err = run_cli("backlinks", "Projects/Alpha.md", "--vault", str(root))
    assert code == 0
    assert "index.md:1" in out and "index.md:2" in out and "[[Alpha]]" in out
    assert "3 backlinks from 2 notes" in out


def test_log_human_json_limit_and_undone_marker(run_cli, make_vault):
    root = write_vault(make_vault)
    code, out, _err = run_cli("log", "--vault", str(root))
    assert code == 0 and "journal is empty" in out
    run_cli("mv", "Projects/Alpha.md", "A1.md", "--vault", str(root))
    run_cli("mv", "A1.md", "A2.md", "--vault", str(root))
    run_cli("undo", "--vault", str(root))
    code, out, _err = run_cli("log", "--vault", str(root))
    assert code == 0
    lines = out.strip().splitlines()
    assert lines[0].startswith("#2") and "(undone)" in lines[0]
    assert lines[1].startswith("#1") and "(undone)" not in lines[1]
    code, out, _err = run_cli("log", "--json", "--limit", "1", "--vault", str(root))
    assert code == 0
    payload = json.loads(out)
    assert [t["id"] for t in payload["transactions"]] == [2]


def test_undo_via_cli_round_trips_and_dry_run_is_safe(run_cli, make_vault):
    root = write_vault(make_vault)
    original = (root / "index.md").read_text(encoding="utf-8")
    run_cli("mv", "Projects/Alpha.md", "Archive/Alpha.md", "--vault", str(root))
    code, out, _err = run_cli("undo", "--dry-run", "--vault", str(root))
    assert code == 0
    assert "would undo transaction #1" in out
    assert (root / "Archive/Alpha.md").exists()  # dry run: still applied
    code, out, _err = run_cli("undo", "--vault", str(root))
    assert code == 0 and "undid transaction #1" in out
    assert (root / "index.md").read_text(encoding="utf-8") == original
    assert (root / "Projects/Alpha.md").exists()


def test_undo_conflict_exits_1_then_force_succeeds(run_cli, make_vault):
    root = write_vault(make_vault)
    run_cli("mv", "Projects/Alpha.md", "Archive/Alpha.md", "--vault", str(root))
    (root / "index.md").write_text("drifted", encoding="utf-8")
    code, _out, err = run_cli("undo", "--vault", str(root))
    assert code == 1
    assert "refused" in err and "--force" in err
    code, out, _err = run_cli("undo", "--force", "--vault", str(root))
    assert code == 0 and "undid transaction #1" in out


def test_full_reorganization_stays_link_clean(run_cli, make_vault):
    # The headline promise, end to end: move a folder, check, undo, check.
    root = make_vault(
        {
            "index.md": "[a](proj/a.md) [[b]]\n",
            "proj/a.md": "[home](../index.md) ![i](img/pic.png)\n",
            "proj/b.md": "[a](a.md)\n",
            "proj/img/pic.png": b"png",
        }
    )
    assert run_cli("check", "--vault", str(root))[0] == 0
    assert run_cli("mv", "proj", "archive/proj", "--vault", str(root))[0] == 0
    assert run_cli("check", "--vault", str(root))[0] == 0
    assert run_cli("undo", "--vault", str(root))[0] == 0
    assert run_cli("check", "--vault", str(root))[0] == 0
