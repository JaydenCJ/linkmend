"""Shared fixtures: build throwaway vaults and drive the real CLI in-process.

Everything runs offline against ``tmp_path``; no network, no clocks, no
global state. ``run_cli`` invokes :func:`linkmend.cli.main` with an argv
list and captures stdout/stderr, so CLI tests exercise the exact code path
the console script uses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

import pytest

from linkmend.cli import main
from linkmend.vault import build_index


@pytest.fixture()
def make_vault(tmp_path):
    """Factory: ``make_vault({"index.md": "...", "img/logo.png": b"..."})``.

    Returns the vault root. Text values are written UTF-8; bytes verbatim.
    """

    counter = {"n": 0}

    def _make(files: Dict[str, object]) -> Path:
        root = tmp_path / f"vault{counter['n']}"  # fresh root on every call
        counter["n"] += 1
        root.mkdir()
        for rel, content in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                target.write_bytes(content)
            else:
                target.write_text(content, encoding="utf-8")
        return root

    return _make


@pytest.fixture()
def run_cli(capsys):
    """Invoke the CLI in-process; returns ``(exit_code, stdout, stderr)``."""

    def _run(*argv: str) -> Tuple[int, str, str]:
        code = main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


def index_of(root: Path):
    """Small helper: fresh index for a vault root."""
    return build_index(root)
