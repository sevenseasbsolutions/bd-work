"""The pool: how a find becomes everybody else's work, and how the three
lists a BD sees are built from it.

There is no cycle here and nothing to open or close. A profile logs a job,
every other live profile is handed it the same second, and it sits on their
list until somebody deals with it.

Every read below takes an optional `since`/`until` day. That is one window
applied everywhere at once — the lists, the tiles above them and the manager's
totals — so a date range can never mean one thing on a screen and another in
the number printed beside it.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .matching import fingerprint
from .models import Application, Assignment, Job, Profile, utcnow


# --------------------------------------------------------------------------- #
# Which day a row belongs to
# --------------------------------------------------------------------------- #

# The entry grid stamps YYYY-MM-DD, but the date column stays editable and
# somebody backfilling yesterday types whatever they type. Each shape here is
# one people really use; anything else falls through to the timestamp the row
# was filed at, which is never wrong, only less precise than what was meant.
_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d",
            "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y", "%d %b", "%d %B")


def as_date(typed: object, fallback: datetime | None) -> date | None:
    """The day a row counts against: what was typed, or when it was filed."""
    text = re.sub(r"[,\s]+", " ", str(typed or "")).strip()
    if text:
        for shape in _FORMATS:
            try:
                parsed = datetime.strptime(text, shape)
            except ValueError:
                continue
            # A date with no year means this year. Left alone, strptime hands
            # back 1900 and the row drops out of every window there is.
            if "%Y" not in shape:
                parsed = parsed.replace(year=(fallback or utcnow()).year)
            return parsed.date()
    return fallback.date() if fallback else None


def within(day: date | None, since: date | None, until: date | None) -> bool:
    """Whether a row falls inside the window. No window means everything."""
    if since is None and until is None:
        return True
    if day is None:
        # A row with no date at all cannot be shown to be inside the window,
        # and counting it anyway makes a filtered total larger than it is.
        return False
    return (since is None or day >= since) and (until is None or day <= until)


def parse_day(value: str | None) -> date | None:
    """A YYYY-MM-DD query parameter. Raises ValueError on anything else."""
    if not value or not value.strip():
        return None
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #

def live_profiles(db: Session) -> list[int]:
    """Every profile a find can be handed to. Read once per import, not per row."""
    return list(db.scalars(select(Profile.id).where(Profile.is_active.is_(True))).all())


def fan_out(db: Session, job: Job, finder_id: int | None,
            live: list[int] | None = None) -> int:
    """Put `job` on every other live profile's list. Returns how many got it.

    Skipped for a profile that already applied for it — through its own find or
    an earlier hand-over — because an application is all-time and is never
    re-issued. Skipped, too, for one that already has a row: a second find of
    the same posting must not resurrect a job somebody turned down last week.

    `live` is the same query, done once by a caller filing thousands of rows in
    a row. Three thousand lines of somebody's old sheet is three thousand
    identical reads of the profile table otherwise.
    """
    if live is None:
        live = live_profiles(db)
    live = [profile_id for profile_id in live if profile_id != finder_id]
    if not live:
        return 0

    spoken_for = set(db.scalars(
        select(Application.profile_id).where(Application.job_id == job.id)).all())
    spoken_for |= set(db.scalars(
        select(Assignment.profile_id).where(Assignment.job_id == job.id)).all())

    made = 0
    for profile_id in live:
        if profile_id in spoken_for:
            continue
        db.add(Assignment(job_id=job.id, profile_id=profile_id, status="pending"))
        made += 1
    return made


def backfill(db: Session, profile: Profile) -> int:
    """Hand a profile the pool that already exists.

    Called when a profile is created or switched back on. Without it a new
    identity has an empty others' jobs list until somebody, somewhere, happens
    to find another job — which is the person with the most spare capacity
    being the one given nothing to do.
    """
    if not profile.is_active:
        return 0
    taken = set(db.scalars(
        select(Application.job_id).where(Application.profile_id == profile.id)).all())
    taken |= set(db.scalars(
        select(Assignment.job_id).where(Assignment.profile_id == profile.id)).all())

    made = 0
    for job_id, found_by in db.execute(select(Job.id, Job.found_by_id)).all():
        if job_id in taken or found_by == profile.id:
            continue
        db.add(Assignment(job_id=job_id, profile_id=profile.id, status="pending"))
        made += 1
    return made


def log_find(db: Session, profile: Profile, row: dict,
             live: list[int] | None = None, import_id: int | None = None) -> dict:
    """Record a job this profile found and applied for. The only way in.

    Returns {"status": ..., "job": Job}. `status` is one of:
      added      new posting, now on everybody else's list
      known      the posting was already in the pool; this profile joins it
      duplicate  this profile has applied for it before — nothing changes
      unusable   not enough typed to identify a posting at all
    """
    fp, _tier = fingerprint(row.get("url"), row.get("title"), row.get("company"))
    if not fp:
        return {"status": "unusable", "job": None}

    job = db.scalar(select(Job).where(Job.fingerprint == fp))
    fresh = job is None
    if fresh:
        job = Job(
            fingerprint=fp,
            title=(row.get("title") or "").strip()[:300],
            company=(row.get("company") or "").strip()[:200],
            platform=(row.get("platform") or "").strip()[:120],
            url=(row.get("url") or "").strip(),
            found_by_id=profile.id,
        )
        db.add(job)
        db.flush()
    else:
        # A second find fills in whatever the first one left blank. It never
        # overwrites: the profile that found it first typed what it saw.
        for field in ("title", "company", "platform", "url"):
            if not getattr(job, field) and row.get(field):
                setattr(job, field, str(row[field]).strip())

    existing = db.scalar(select(Application).where(
        Application.job_id == job.id, Application.profile_id == profile.id))
    if existing:
        return {"status": "duplicate", "job": job}

    # `import_id` marks where the line came from and nothing else. It is not a
    # kind of application: an imported row is an own job and counts as one.
    db.add(Application(job_id=job.id, profile_id=profile.id, source="own",
                       email=(row.get("email") or "").strip()[:255],
                       applied_on=(row.get("applied_on") or "").strip()[:40],
                       import_id=import_id))
    # A find that lands on a job already sitting on this profile's list means
    # the BD went and applied without touching the button. Close that row off
    # rather than leaving it pending against an application that exists.
    standing = db.scalar(select(Assignment).where(
        Assignment.job_id == job.id, Assignment.profile_id == profile.id))
    if standing and standing.status == "pending":
        standing.status = "applied"
        standing.status_changed_at = utcnow()

    fan_out(db, job, profile.id, live)
    return {"status": "added" if fresh else "known", "job": job}


def set_status(db: Session, assignment: Assignment, status: str,
               applied_on: str = "") -> None:
    """Apply for, or turn down, an others' job.

    Applying writes an Application with source 'others' — the row that makes
    the split on the manager's screen real. Undoing back to pending takes it
    away again, because an application nobody made should not be counted.
    """
    assignment.status = status
    assignment.status_changed_at = utcnow()

    existing = db.scalar(select(Application).where(
        Application.job_id == assignment.job_id,
        Application.profile_id == assignment.profile_id))

    if status == "applied" and not existing:
        db.add(Application(job_id=assignment.job_id, profile_id=assignment.profile_id,
                           source="others", applied_on=applied_on.strip()[:40]))
    elif status != "applied" and existing and existing.source == "others":
        db.delete(existing)


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #

def _job_dict(job: Job) -> dict:
    return {"id": job.id, "title": job.title, "company": job.company,
            "platform": job.platform, "url": job.url,
            "first_seen": job.first_seen.isoformat() if job.first_seen else None}


def _acted(assignment: Assignment) -> datetime | None:
    """When an others' job last mattered: when it was dealt with, or handed over."""
    return assignment.status_changed_at or assignment.created_at


def applicants(db: Session, job_ids: list[int]) -> dict[int, list[dict]]:
    """{job_id: [{profile, source}]} — who has already approached each posting.

    Never narrowed by the date window. This column answers "is anybody already
    in front of this client", and the honest answer to that does not change
    because somebody is looking at last week.
    """
    if not job_ids:
        return {}
    rows = db.execute(
        select(Application.job_id, Profile.name, Application.source)
        .join(Profile, Profile.id == Application.profile_id)
        .where(Application.job_id.in_(job_ids))
        .order_by(Profile.name)
    ).all()
    out: dict[int, list[dict]] = {}
    for job_id, name, source in rows:
        out.setdefault(job_id, []).append({"profile": name, "source": source})
    return out


def own_jobs(db: Session, profile_id: int, since: date | None = None,
             until: date | None = None) -> list[dict]:
    """What this profile went out and found."""
    rows = db.execute(
        select(Application, Job).join(Job, Job.id == Application.job_id)
        .where(Application.profile_id == profile_id, Application.source == "own")
        .order_by(Application.created_at.desc(), Application.id.desc())
    ).all()
    rows = [(app, job) for app, job in rows
            if within(as_date(app.applied_on, app.created_at), since, until)]

    who = applicants(db, [job.id for _, job in rows])
    me = _name(db, profile_id)
    return [{
        "application_id": app.id,
        "email": app.email,
        "applied_on": app.applied_on,
        "logged_at": app.created_at.isoformat() if app.created_at else None,
        # Colleagues only. This profile is on every one of these by definition,
        # so listing it back would be noise on every single row.
        "also_applied": [w["profile"] for w in who.get(job.id, []) if w["profile"] != me],
        **_job_dict(job),
    } for app, job in rows]


def others_jobs(db: Session, profile_id: int, status: str = "pending",
                since: date | None = None, until: date | None = None) -> list[dict]:
    """What other profiles found and handed over, at one status."""
    rows = db.execute(
        select(Assignment, Job, Profile.name)
        .join(Job, Job.id == Assignment.job_id)
        .outerjoin(Profile, Profile.id == Job.found_by_id)
        .where(Assignment.profile_id == profile_id, Assignment.status == status)
        .order_by(Assignment.created_at.desc(), Assignment.id.desc())
    ).all()
    rows = [triple for triple in rows
            if within(as_date("", _acted(triple[0])), since, until)]

    who = applicants(db, [job.id for _, job, _ in rows])
    return [{
        "assignment_id": row.id,
        "status": row.status,
        "found_by": found_by or "",
        "applied_by": [w["profile"] for w in who.get(job.id, [])],
        **_job_dict(job),
    } for row, job, found_by in rows]


def _name(db: Session, profile_id: int) -> str:
    return db.scalar(select(Profile.name).where(Profile.id == profile_id)) or ""


def all_jobs(db: Session, profile_id: int | None = None, since: date | None = None,
             until: date | None = None) -> list[dict]:
    """The whole pool. With a profile, every row carries that profile's standing.

    standing is one of: own, applied, skipped, pending, none. The window here is
    on when the posting was first seen — "the jobs that came in that week".
    """
    rows = db.execute(
        select(Job, Profile.name).outerjoin(Profile, Profile.id == Job.found_by_id)
        .order_by(Job.first_seen.desc(), Job.id.desc())
    ).all()
    rows = [(job, found_by) for job, found_by in rows
            if within(as_date("", job.first_seen), since, until)]

    ids = [job.id for job, _ in rows]
    who = applicants(db, ids)

    mine: dict[int, str] = {}
    # This profile's own entry line for the row, so a copied row carries the
    # address it went out from and the date it went out — the two columns the
    # spreadsheet this replaces was really keeping.
    entry: dict[int, tuple[str, str]] = {}
    if profile_id and ids:
        for job_id, source, email, applied_on in db.execute(
            select(Application.job_id, Application.source,
                   Application.email, Application.applied_on)
            .where(Application.profile_id == profile_id, Application.job_id.in_(ids))
        ).all():
            mine[job_id] = "own" if source == "own" else "applied"
            entry[job_id] = (email, applied_on)
        for job_id, status in db.execute(
            select(Assignment.job_id, Assignment.status)
            .where(Assignment.profile_id == profile_id, Assignment.job_id.in_(ids))
        ).all():
            # An application always wins the label: a row that was handed over
            # and then applied for is "applied", not "pending".
            if job_id not in mine:
                mine[job_id] = "skipped" if status == "skipped" else "pending"

    return [{
        "found_by": found_by or "",
        "applied_by": [w["profile"] for w in who.get(job.id, [])],
        "applications": len(who.get(job.id, [])),
        "standing": mine.get(job.id, "none"),
        "my_email": entry.get(job.id, ("", ""))[0],
        "my_date": entry.get(job.id, ("", ""))[1],
        **_job_dict(job),
    } for job, found_by in rows]


def profile_counts(db: Session, since: date | None = None,
                   until: date | None = None) -> dict[int, dict]:
    """Every number on the manager's screen, one row per profile.

    Five counts, and they are the five words the whole app uses: own jobs,
    others' jobs given, of those applied for, of those skipped, and what is
    still pending.

    Counted in Python rather than with a GROUP BY, because the day a row counts
    against is the day somebody typed into the date column — free text that SQL
    cannot compare. The data here is small enough that the simpler correct
    thing wins.
    """
    own: dict[int, int] = {}
    from_others: dict[int, int] = {}
    given: dict[int, int] = {}
    skipped: dict[int, int] = {}
    pending: dict[int, int] = {}

    def bump(bucket: dict[int, int], key: int) -> None:
        bucket[key] = bucket.get(key, 0) + 1

    for profile_id, source, applied_on, created_at in db.execute(
        select(Application.profile_id, Application.source,
               Application.applied_on, Application.created_at)
    ).all():
        if not within(as_date(applied_on, created_at), since, until):
            continue
        bump(own if source == "own" else from_others, profile_id)

    for profile_id, status, created_at, changed in db.execute(
        select(Assignment.profile_id, Assignment.status,
               Assignment.created_at, Assignment.status_changed_at)
    ).all():
        if not within(as_date("", changed or created_at), since, until):
            continue
        bump(given, profile_id)
        if status == "skipped":
            bump(skipped, profile_id)
        elif status == "pending":
            bump(pending, profile_id)

    out = {}
    for profile_id in db.scalars(select(Profile.id)).all():
        o, f = own.get(profile_id, 0), from_others.get(profile_id, 0)
        out[profile_id] = {
            "own": o,
            "given": given.get(profile_id, 0),
            "from_others": f,
            "skipped": skipped.get(profile_id, 0),
            "pending": pending.get(profile_id, 0),
            "applied": o + f,
        }
    return out
