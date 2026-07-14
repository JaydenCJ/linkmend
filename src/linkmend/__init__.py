"""linkmend — move and rename Markdown notes without breaking a single link.

Public API surface (everything else is internal and may change):

- :func:`linkmend.vault.build_index` / :class:`linkmend.vault.VaultIndex`
- :func:`linkmend.links.scan_links` / :class:`linkmend.links.Link`
- :func:`linkmend.plan.plan_move` / :class:`linkmend.plan.MovePlan`
- :func:`linkmend.apply.apply_plan`
- :func:`linkmend.journal.record_transaction` /
  :func:`linkmend.journal.undo_transaction`
- :func:`linkmend.check.check_vault` / :func:`linkmend.check.find_backlinks`
"""

from .apply import apply_plan
from .check import check_vault, find_backlinks
from .errors import (
    JournalConflictError,
    JournalError,
    LinkmendError,
    PlanError,
    VaultError,
)
from .journal import load_transactions, record_transaction, undo_transaction
from .links import Link, scan_links
from .plan import MovePlan, plan_move
from .vault import VaultIndex, build_index

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "apply_plan",
    "build_index",
    "check_vault",
    "find_backlinks",
    "load_transactions",
    "plan_move",
    "record_transaction",
    "scan_links",
    "undo_transaction",
    "JournalConflictError",
    "JournalError",
    "Link",
    "LinkmendError",
    "MovePlan",
    "PlanError",
    "VaultError",
    "VaultIndex",
]
