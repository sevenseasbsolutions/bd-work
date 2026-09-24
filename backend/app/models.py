"""The tables MBS needs.

There is no cycle and no batch. Work is a standing pool: a profile logs a job
it found, every other live profile is handed that job, and each one either
applies for it or turns it down. That is the whole machine.

The five at the top are the machine. The three at the bottom are the things
that had to exist once a team arrived carrying three months of history in a
spreadsheet: a switch the manager owns, and the record of what an uploaded
sheet did, line by line.

Vocabulary, used identically in the API and on every screen:

  own job     a job this profile went out and found, and applied for itself
  others' job a job another profile found, handed to this one to apply for
  skipped     an others' job this profile looked at and turned down
  all jobs    the pool, with this profile's standing against every row
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

ROLES = ("manager", "bd")
SOURCES = ("own", "others")
STATUSES = ("pending", "applied", "skipped")


def utcnow() -> datetime:
    """Naive UTC. Every timestamp in this schema is one; nothing converts."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """Somebody who signs in. A manager runs the workspace, a BD works profiles.

    There is no developer role here on purpose — nobody sits an interview in
    this app because this app does not know interviews exist.
    """
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="bd")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    profiles: Mapped[list["Profile"]] = relationship(back_populates="user")


class Profile(Base):
    """The identity a job is applied under — "Khuram, AI Engineer".

    The unit of work is the profile, never the person: one BD may run several,
    and a profile can be handed to a different BD without its history moving.
    """
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    headline: Mapped[str] = mapped_column(String(160), default="")
    platform: Mapped[str] = mapped_column(String(120), default="")
    skills: Mapped[str] = mapped_column(String(400), default="")
    # The BD who runs this identity. Empty until a manager assigns it, and a
    # profile nobody holds is dispatched to nobody.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # The Google Sheet this profile is mirrored into — the long string out of
    # the middle of the spreadsheet's URL, or empty for a profile that is not
    # mirrored anywhere. On the profile and not on the BD because the profile
    # is the unit of work: one person running two identities is two candidates
    # to a client, and a client's sheet should not have the other one in it.
    # The credentials stay global; only which spreadsheet varies.
    sheet_id: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User | None] = relationship(back_populates="profiles")


class Platform(Base):
    """A place jobs come from, as offered in the entry grid's dropdown.

    A table rather than a constant, because which boards a team works changes
    faster than anybody wants to ship a release for. The job itself still keeps
    the platform as plain text: taking a board off this list changes what the
    dropdown offers next time, never what somebody already recorded.
    """
    __tablename__ = "platforms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Job(Base):
    """A posting, identified by fingerprint rather than by URL.

    Global, not per-profile: the point of the pool is that one posting is one
    row however many people paste a different referral link to it.
    """
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(400), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    company: Mapped[str] = mapped_column(String(200), default="")
    platform: Mapped[str] = mapped_column(String(120), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    # Who put it in the pool. Every other profile's copy is an others' job
    # because of this column.
    found_by_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id"), index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Application(Base):
    """This profile has approached this job.

    Normally once per (job, PROFILE): the entry grid warns when the BD has
    applied for the posting before, under this profile or any other they run,
    and files nothing until they say so. A BD who presses Ignore is reapplying
    on purpose, and that second application is a second row — which is why
    there is no unique constraint here any more (schema.py drops the old one).
    """
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)
    # 'own' if this profile found it, 'others' if it arrived off somebody
    # else's find. The split every number on the manager's screen is made of.
    source: Mapped[str] = mapped_column(String(8), default="own")
    # The address this application went out from. On the application and not on
    # the profile, because one identity does not always apply from one inbox,
    # and not on the job, because two profiles applying to one posting each
    # used their own.
    email: Mapped[str] = mapped_column(String(255), default="")
    # What the BD typed, kept verbatim. The entry form stamps today for them.
    applied_on: Mapped[str] = mapped_column(String(40), default="")
    # The upload this arrived on, or NULL for a line somebody typed. Only the
    # Google Sheet mirror reads it, to honour the manager's switch about
    # whether three months of imported history belongs in the spreadsheet. It
    # is deliberately not a `source` value: an imported row IS an own job, and
    # every count on every screen must go on treating it as one.
    #
    # A plain Integer, with no foreign key and no index, on purpose. `schema.py`
    # can only ALTER a column in with its type and its default — never a
    # constraint, never an index — so either would give a fresh database
    # something an upgraded one silently lacks, and the two would stop being the
    # same schema. Neither is missed: nothing joins on this, it is only ever
    # read as "NULL or not", and every query that reads it is already narrowed
    # by the primary key.
    import_id: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Assignment(Base):
    """An others' job sitting on one profile's list.

    Created the moment somebody else logs a find, and it never expires —
    nothing here is scoped to a cycle, so a job handed over on Monday is still
    on the list on Friday until it is applied for or turned down.
    """
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("job_id", "profile_id", name="uq_assignment"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # Why the BD turned it down. Asked for on every Skip, cleared when the row
    # goes back to pending or is applied for.
    skip_reason: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime)


class Setting(Base):
    """One workspace-wide switch, owned by the manager, read by every screen.

    A table with two text columns rather than a column per switch, because a
    switch is a thing a manager turns on one afternoon and a column is a
    migration. `settings.DEFAULTS` says what a key means when nobody has
    written a row for it, so an empty table is a working workspace.
    """
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(200), default="")


class Import(Base):
    """One upload of an old sheet, and what became of every line in it.

    The five counts add up to `rows` exactly — that is the point of keeping
    them. A BD who uploads three thousand lines and is told two thousand seven
    hundred and fifty went in wants the other two hundred and fifty accounted
    for, not rounded off.

    `digest` is the file's SHA-256. It is what lets the screen say "you
    uploaded this same sheet on Tuesday" rather than leaving somebody to wonder
    whether they are about to double everything.
    """
    __tablename__ = "imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)
    # Who pressed the button. Nulled rather than cascaded when that person is
    # deleted, for the same reason a profile outlives the BD who ran it.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255), default="")
    digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    sheets: Mapped[str] = mapped_column(String(400), default="")

    rows: Mapped[int] = mapped_column(Integer, default=0)
    added: Mapped[int] = mapped_column(Integer, default=0)
    known: Mapped[int] = mapped_column(Integer, default=0)
    duplicate: Mapped[int] = mapped_column(Integer, default=0)
    repeated: Mapped[int] = mapped_column(Integer, default=0)
    not_applied: Mapped[int] = mapped_column(Integer, default=0)
    unusable: Mapped[int] = mapped_column(Integer, default=0)
    # False while rows are still going in, and left False if the run died
    # halfway. A half-finished import is not a failure — the lines that landed
    # are filed, and uploading the same sheet again picks up the rest.
    finished: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ImportRow(Base):
    """A line of an uploaded sheet that could not be filed, kept verbatim.

    Only the unusable ones are stored. Everything else is either in the pool or
    was already there, and a copy of it here would be a second version of the
    truth. These exist so the BD can download them, fix them and upload again —
    which is the whole promise of the feature: nothing is silently dropped.
    """
    __tablename__ = "import_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("imports.id"), index=True)
    sheet: Mapped[str] = mapped_column(String(64), default="")
    # The row number in the sheet as Excel shows it, so "line 812" can be found.
    line: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(120), default="")

    company: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(300), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    platform: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    applied_on: Mapped[str] = mapped_column(String(40), default="")
