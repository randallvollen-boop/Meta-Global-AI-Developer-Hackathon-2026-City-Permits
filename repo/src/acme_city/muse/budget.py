"""The daily allowance of provider calls.

The allowance is one number for the whole day and it is shared by every
provider path.  A call is reserved before it is dispatched, so a call that
fails or times out still counts, and a restart reads the same counter instead
of handing out a fresh allowance.

The day is the UTC day: the allowance is spent at midnight UTC.
"""
# REQUIRES: AI-01, AI-03
# The provider boundary reserves one call of the daily allowance before it dispatches.

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from acme_city.core.clock import utc_now
from acme_city.core.ids import new_id
from acme_city.muse.client import MuseRequestError
from acme_city.persistence.models import agent_ops

class MuseBudgetExceeded(MuseRequestError):
    """The daily allowance of provider calls is used up.

    It is raised before the provider is contacted, so a refused call sends
    nothing and costs nothing.
    """


class MuseBudget:
    """The daily allowance of provider calls.

    The budget holds the counter of the day and the cap the day allows.  The
    reservation is one statement, so two callers cannot take the same call:
    the counter only grows while the day still has room.
    """

    def __init__(
        self,
        session: Session,
        *,
        settings: Any,
        now: datetime | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._now = now

    # ------------------------------------------------------------------ reads

    @property
    def cap(self) -> int:
        """Return the number of calls the day allows."""
        value = getattr(self._settings, "muse_daily_call_cap", 0)
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    def _moment(self) -> datetime:
        """Return the moment the budget reads."""
        return self._now if self._now is not None else utc_now()

    def day(self) -> str:
        """Return the day the allowance is counted in."""
        return self._moment().astimezone(timezone.utc).date().isoformat()

    def used(self) -> int:
        """Return the number of calls the day already reserved."""
        row = self._session.execute(
            select(agent_ops.MuseDailyBudget).where(
                agent_ops.MuseDailyBudget.day == self.day()
            )
        ).scalar_one_or_none()
        return 0 if row is None else int(row.calls_used)

    # -------------------------------------------------------------- reservation

    def reserve(self) -> None:
        """Reserve one call of the day, or refuse the call.

        Raises:
            MuseBudgetExceeded: when the day has no room left.
        """
        cap = self.cap
        if cap <= 0:
            raise MuseBudgetExceeded(
                "the daily allowance of provider calls is zero in this deployment"
            )
        day = self.day()
        # The row of the day is written once; a second writer of the same day
        # keeps the row that is already there.
        self._session.execute(
            sqlite_insert(agent_ops.MuseDailyBudget)
            .values(id=new_id("musebudget"), day=day, calls_used=0)
            .on_conflict_do_nothing(index_elements=["day"])
        )
        result = self._session.execute(
            update(agent_ops.MuseDailyBudget)
            .where(
                agent_ops.MuseDailyBudget.day == day,
                agent_ops.MuseDailyBudget.calls_used < cap,
            )
            .values(calls_used=agent_ops.MuseDailyBudget.calls_used + 1)
        )
        if result.rowcount == 0:
            raise MuseBudgetExceeded(
                f"the daily allowance of {cap} provider call(s) is used up"
            )


__all__ = [
    "MuseBudget",
    "MuseBudgetExceeded",
]
