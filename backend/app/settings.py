"""The switches a manager owns and everybody else reads.

One table, two text columns. A switch is something a manager turns on for the
team one afternoon; a column per switch would make that a release. `DEFAULTS`
says what each key means when no row has been written for it, so an empty
table is a working workspace and adding a switch never needs a data fix.

Values are stored as the text "on" or "off" and handed to the API as booleans,
because a screen wants a checkbox and a database wants something it can print.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Setting

# Every switch there is, with the answer for a workspace that has never been
# asked. `select_all` starts on: a team that has just imported three months of
# history has thousands of pending rows and no other way through them.
DEFAULTS: dict[str, bool] = {
    "select_all": True,
    # The Google Sheet mirror. Off until somebody has put the credentials and
    # the spreadsheet id in front of it, because a switch that is on and cannot
    # work is a switch that lies.
    "sheet_sync": False,
    # Whether an uploaded sheet goes into the mirror too. Off, because the two
    # are wanted for different reasons: the mirror is normally a live record of
    # what the team is finding now, and one BD bringing three months of history
    # across would bury that under thousands of rows nobody was waiting for. A
    # manager who does want the whole history there turns this on.
    "sheet_sync_imports": False,
}

ON, OFF = "on", "off"


def all_settings(db: Session) -> dict[str, bool]:
    """Every switch, defaults filled in. The shape the API hands out."""
    stored = {key: value for key, value in db.execute(
        select(Setting.key, Setting.value)).all()}
    return {key: (stored[key] == ON if key in stored else fallback)
            for key, fallback in DEFAULTS.items()}


def get(db: Session, key: str) -> bool:
    """One switch. Unknown keys are False rather than an exception: a caller
    asking about a switch that no longer exists should read as "off", not
    bring down the request it was checked in."""
    if key not in DEFAULTS:
        return False
    return all_settings(db)[key]


def raw_get(db: Session, key: str, fallback: str = "") -> str:
    """A stored value that is not a switch — a sync watermark, say.

    Kept here rather than read straight out of the table elsewhere, so that
    every write to `settings` still goes through one module. Keys read this way
    are not in DEFAULTS and so never appear in `all_settings`: the manager's
    screen offers switches, not bookkeeping.
    """
    row = db.get(Setting, key)
    return row.value if row and row.value != "" else fallback


def raw_put(db: Session, key: str, value: str) -> None:
    """Store a non-switch value. Does not commit — the caller owns that."""
    row = db.get(Setting, key)
    if row:
        row.value = value[:200]
    else:
        db.add(Setting(key=key, value=value[:200]))


def put(db: Session, key: str, on: bool) -> None:
    """Set one switch. Does not commit — the caller owns the transaction."""
    if key not in DEFAULTS:
        raise KeyError(key)
    row = db.get(Setting, key)
    if row:
        row.value = ON if on else OFF
    else:
        db.add(Setting(key=key, value=ON if on else OFF))
