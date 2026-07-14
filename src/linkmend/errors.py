"""Exception hierarchy for linkmend.

Every error the tool raises on purpose derives from :class:`LinkmendError`,
so the CLI can catch one type, print one readable line, and pick an exit
code. Raw tracebacks are reserved for actual bugs.
"""

from __future__ import annotations

from typing import List


class LinkmendError(Exception):
    """Base class for all errors linkmend raises deliberately."""


class VaultError(LinkmendError):
    """The vault root is missing, unreadable, or a path escapes it."""


class PlanError(LinkmendError):
    """A move cannot be planned or applied safely (conflicts, bad paths)."""


class JournalError(LinkmendError):
    """The undo journal is missing, corrupt, or the request is invalid."""


class JournalConflictError(JournalError):
    """Undo verification failed: the vault changed since the transaction.

    ``problems`` holds one human-readable line per conflict so the CLI can
    list exactly which files drifted and why the undo was refused.
    """

    def __init__(self, problems: List[str]) -> None:
        self.problems = list(problems)
        summary = "; ".join(self.problems[:3])
        if len(self.problems) > 3:
            summary += f"; and {len(self.problems) - 3} more"
        super().__init__(f"vault changed since this transaction: {summary}")
