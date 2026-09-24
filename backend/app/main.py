"""MBS — the whole API.

Three nouns and nothing else: people, profiles, jobs. A manager adds people,
adds profiles and says who runs which. A BD opens a profile and works three
lists — own jobs, others' jobs, all jobs. There is no cycle to start, no
interview, no assessment and no client record, because none of those are what
this app is for.

A sheet can be uploaded, and it is the one thing here that is not a new noun: an
upload is a run of entry-grid lines filed in one go, against the same pool, by
the same code. See imports.py.
"""
from __future__ import annotations

import asyncio
import os
import urllib.parse
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import dispatch, exports, imports, settings, sheets
from .db import Base, SessionLocal, engine, get_db
from .models import (Application, Assignment, Import, ImportRow, Job, Platform,
                     Profile, User)
from .schema import drop_retired_constraints, sync_columns
from .security import (check_password, current_user, hash_password,
                       make_token, manager_only)

def boot() -> None:
    """Make the tables, and the first manager if there is nobody at all.

    A workspace with no way in is a workspace nobody can set up, so the very
    first boot mints one account. Change the password and clear the variables.
    """
    Base.metadata.create_all(engine)
    # create_all leaves an existing table alone, so a database made before a
    # column was added needs that column putting on. See schema.py.
    sync_columns(engine)
    drop_retired_constraints(engine)
    with SessionLocal() as db:
        # The starting list of boards. Seeded only when the table is empty, so
        # a board the manager deletes does not come back on the next restart.
        if not db.scalar(select(func.count()).select_from(Platform)):
            for name in ("Upwork", "LinkedIn", "Indeed", "Freelancer",
                         "Glassdoor", "Wellfound", "Company site", "Other"):
                db.add(Platform(name=name))
            db.commit()
        if db.scalar(select(func.count()).select_from(User)):
            return
        db.add(User(
            email=os.environ.get("MBS_ADMIN_EMAIL", "manager@mbs.co").lower(),
            name=os.environ.get("MBS_ADMIN_NAME", "Manager"),
            password_hash=hash_password(os.environ.get("MBS_ADMIN_PASSWORD", "manager")),
            role="manager",
        ))
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    boot()
    # The Google Sheet mirror, if there is a service account to write with.
    # Started whatever the manager's switch says, and whether or not any sheet
    # exists yet: both are things that change during the day — a switch flipped,
    # a link pasted against a profile — and a loop that had to be restarted for
    # either would make turning the sheet on a deploy. Each pass reads them.
    mirror = asyncio.create_task(sheets.run()) if sheets.credentials() else None
    try:
        yield
    finally:
        if mirror:
            mirror.cancel()
            try:
                await mirror
            except asyncio.CancelledError:
                pass


app = FastAPI(title="MBS", version="1.0.0", lifespan=lifespan)

# The frontend is served from a different port in development and from the same
# origin in production, so allowing everything costs nothing and saves a
# config file nobody would remember to update.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    # The browser hides every response header from a cross-origin fetch unless
    # it is named here, and the download needs this one to know what to call
    # the file it has just been handed.
    expose_headers=["Content-Disposition"],
)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def attachment(filename: str) -> dict:
    """Content-Disposition for a filename that may not be ASCII.

    Two spellings on purpose: `filename` is the plain fallback every browser
    understands, `filename*` is the real one. A profile called
    "Khuram — AI Engineer" has an em dash in it, and sending only the raw bytes
    is what turns a download into a header parse error.
    """
    plain = filename.encode("ascii", "ignore").decode("ascii").replace('"', "")
    plain = " ".join(plain.split()) or "MBS export.xlsx"
    quoted = urllib.parse.quote(filename)
    return {"Content-Disposition":
            f'attachment; filename="{plain}"; filename*=UTF-8\'\'{quoted}'}


# --------------------------------------------------------------------------- #
# Shapes
# --------------------------------------------------------------------------- #

class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=4, max_length=128)
    role: str = "bd"


class UserPatch(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    password: str | None = None
    role: str | None = None
    is_active: bool | None = None


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    headline: str = ""
    platform: str = ""
    skills: str = ""
    user_id: int | None = None


class ProfilePatch(BaseModel):
    name: str | None = None
    headline: str | None = None
    platform: str | None = None
    skills: str | None = None
    # Explicitly nullable: 0 or null means "take it off whoever holds it".
    user_id: int | None = None
    is_active: bool | None = None


class JobIn(BaseModel):
    """One line of the entry grid, in the order it is typed:
    client, job title, link, platform, the address it went out from, the date."""
    company: str = ""
    title: str = ""
    url: str = ""
    platform: str = ""
    email: str = ""
    applied_on: str = ""
    # The Ignore button: the BD was told they applied for this before and is
    # filing it again on purpose.
    reapply: bool = False


class FindsIn(BaseModel):
    """One line of the entry grid or fifty. Pressing + New entry commits what is
    filled in, and a block pasted from Excel arrives the same way, so there is
    one code path rather than one per way of typing."""
    jobs: list[JobIn]


class StatusIn(BaseModel):
    status: str
    applied_on: str = ""
    # Why a job was skipped. The screen asks for it on every Skip.
    reason: str = Field("", max_length=300)


class PlatformIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class BulkIn(BaseModel):
    """Select all, then Applied or Skip. One request, not one per row.

    Capped because the button behind it says "all 3,000" after a sheet import,
    and a list that long wants to be a considered number rather than whatever
    the browser happened to send.
    """
    ids: list[int] = Field(min_length=1, max_length=5000)
    status: str
    applied_on: str = ""
    reason: str = Field("", max_length=300)


class SettingsIn(BaseModel):
    """The manager's switches. Absent means leave it as it is."""
    select_all: bool | None = None
    sheet_sync: bool | None = None
    sheet_sync_imports: bool | None = None


Window = tuple[object, object]


def window(since: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
           until: str | None = Query(None, description="YYYY-MM-DD, inclusive")) -> Window:
    """The date range every list and every count is read through.

    One dependency rather than two parameters written out per route, so a
    screen cannot end up with a list filtered one way and the total printed
    above it filtered another.
    """
    try:
        return dispatch.parse_day(since), dispatch.parse_day(until)
    except ValueError:
        raise HTTPException(400, "Dates must be written YYYY-MM-DD.")


def user_out(user: User) -> dict:
    return {"id": user.id, "name": user.name, "email": user.email,
            "role": user.role, "is_active": user.is_active}


def profile_out(profile: Profile, holder: str = "") -> dict:
    return {"id": profile.id, "name": profile.name, "headline": profile.headline,
            "platform": profile.platform, "skills": profile.skills,
            "user_id": profile.user_id, "bd": holder,
            "is_active": profile.is_active}


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #

@app.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    # One message for a wrong address and a wrong password, so the form cannot
    # be used to find out which addresses exist.
    if not user or not check_password(body.password, user.password_hash):
        raise HTTPException(401, "That email and password do not match.")
    if not user.is_active:
        raise HTTPException(403, "That account has been switched off.")
    return {"token": make_token(user), "user": user_out(user)}


@app.get("/auth/me")
def me(user: User = Depends(current_user)) -> dict:
    return user_out(user)


# --------------------------------------------------------------------------- #
# People — manager only
# --------------------------------------------------------------------------- #

@app.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(manager_only)) -> list[dict]:
    users = db.scalars(select(User).order_by(User.role, User.name)).all()
    held: dict[int, list[str]] = {}
    for name, user_id in db.execute(
        select(Profile.name, Profile.user_id).where(Profile.user_id.isnot(None))
        .order_by(Profile.name)
    ).all():
        held.setdefault(user_id, []).append(name)
    return [{**user_out(u), "profiles": held.get(u.id, [])} for u in users]


@app.post("/users", status_code=201)
def add_user(body: UserIn, db: Session = Depends(get_db),
             _: User = Depends(manager_only)) -> dict:
    if body.role not in ("manager", "bd"):
        raise HTTPException(400, "A person is either a manager or a BD.")
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "Somebody already signs in with that email.")
    user = User(name=body.name.strip(), email=body.email.lower(),
                password_hash=hash_password(body.password), role=body.role)
    db.add(user)
    db.commit()
    return user_out(user)


@app.patch("/users/{user_id}")
def edit_user(user_id: int, body: UserPatch, db: Session = Depends(get_db),
              actor: User = Depends(manager_only)) -> dict:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "No such person.")
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(400, "A person needs a name.")
        user.name = body.name.strip()[:120]
    if body.email is not None and body.email.lower() != user.email:
        if db.scalar(select(User).where(User.email == body.email.lower(),
                                        User.id != user.id)):
            raise HTTPException(409, "Somebody already signs in with that email.")
        user.email = body.email.lower()
    if body.password:
        if len(body.password) < 4:
            raise HTTPException(400, "A password needs at least 4 characters.")
        user.password_hash = hash_password(body.password)
    if body.role is not None and body.role != user.role:
        if body.role not in ("manager", "bd"):
            raise HTTPException(400, "A person is either a manager or a BD.")
        # The same lock-out as switching yourself off: the last screen that
        # could make you a manager again is one only a manager can open.
        if user.id == actor.id:
            raise HTTPException(400, "You cannot change your own role.")
        user.role = body.role
    if body.is_active is not None:
        # Switching yourself off would lock the workspace's only manager out of
        # the screen that could switch them back on.
        if user.id == actor.id and not body.is_active:
            raise HTTPException(400, "You cannot switch your own account off.")
        user.is_active = body.is_active
    db.commit()
    return user_out(user)


@app.delete("/users/{user_id}")
def remove_user(user_id: int, db: Session = Depends(get_db),
                actor: User = Depends(manager_only)) -> dict:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "No such person.")
    if user.id == actor.id:
        raise HTTPException(400, "You cannot delete your own account.")
    # Profiles outlive the person who ran them. Unassigning rather than
    # cascading is the difference between a BD leaving and a quarter of the
    # team's history leaving with them.
    freed = db.scalars(select(Profile).where(Profile.user_id == user.id)).all()
    for profile in freed:
        profile.user_id = None
    # An upload they did outlives them too, for the same reason: the record of
    # where three months of rows came from is the profile's, not theirs.
    for batch in db.scalars(select(Import).where(Import.user_id == user.id)).all():
        batch.user_id = None
    db.delete(user)
    db.commit()
    return {"deleted": user_id, "profiles_unassigned": len(freed)}


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #

@app.get("/profiles")
def list_profiles(db: Session = Depends(get_db), user: User = Depends(current_user),
                  span: Window = Depends(window)) -> list[dict]:
    """A manager sees every profile; a BD sees the ones they hold.

    This is the whole of the BD's navigation — they pick an identity and then
    work its three lists.
    """
    query = select(Profile, User.name).outerjoin(User, User.id == Profile.user_id)
    if user.role != "manager":
        query = query.where(Profile.user_id == user.id, Profile.is_active.is_(True))
    rows = db.execute(query.order_by(Profile.name)).all()
    counts = dispatch.profile_counts(db, *span)
    return [{**profile_out(p, holder or ""), "counts": counts.get(p.id, {})}
            for p, holder in rows]


@app.post("/profiles", status_code=201)
def add_profile(body: ProfileIn, db: Session = Depends(get_db),
                _: User = Depends(manager_only)) -> dict:
    name = body.name.strip()
    if db.scalar(select(Profile).where(func.lower(Profile.name) == name.lower())):
        raise HTTPException(409, "There is already a profile by that name.")
    holder = db.get(User, body.user_id) if body.user_id else None
    if body.user_id and not holder:
        raise HTTPException(404, "No such person to assign it to.")
    profile = Profile(name=name, headline=body.headline.strip(),
                      platform=body.platform.strip(), skills=body.skills.strip(),
                      user_id=holder.id if holder else None)
    db.add(profile)
    db.flush()
    # A new identity starts with the pool everybody else already has, not with
    # an empty list it would take a week of other people's finds to fill.
    handed = dispatch.backfill(db, profile)
    db.commit()
    return {**profile_out(profile, holder.name if holder else ""), "handed_over": handed}


@app.patch("/profiles/{profile_id}")
def edit_profile(profile_id: int, body: ProfilePatch, db: Session = Depends(get_db),
                 _: User = Depends(manager_only)) -> dict:
    profile = db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(404, "No such profile.")
    fields = body.model_dump(exclude_unset=True)

    if "name" in fields and fields["name"]:
        clash = db.scalar(select(Profile).where(
            func.lower(Profile.name) == fields["name"].strip().lower(),
            Profile.id != profile.id))
        if clash:
            raise HTTPException(409, "There is already a profile by that name.")
        profile.name = fields["name"].strip()
    for field in ("headline", "platform", "skills"):
        if field in fields and fields[field] is not None:
            setattr(profile, field, fields[field].strip())
    if "user_id" in fields:
        holder = db.get(User, fields["user_id"]) if fields["user_id"] else None
        if fields["user_id"] and not holder:
            raise HTTPException(404, "No such person to assign it to.")
        profile.user_id = holder.id if holder else None

    handed = 0
    if "is_active" in fields and fields["is_active"] is not None:
        was = profile.is_active
        profile.is_active = fields["is_active"]
        if profile.is_active and not was:
            # Coming back on, it catches up on everything found while it was off.
            handed = dispatch.backfill(db, profile)
        elif not profile.is_active and was:
            # Going off, the work it never got to goes back rather than sitting
            # on a list nobody is looking at.
            db.execute(delete(Assignment).where(
                Assignment.profile_id == profile.id, Assignment.status == "pending"))

    db.commit()
    holder_name = db.scalar(select(User.name).where(User.id == profile.user_id)) or ""
    return {**profile_out(profile, holder_name), "handed_over": handed}


@app.delete("/profiles/{profile_id}")
def remove_profile(profile_id: int, db: Session = Depends(get_db),
                   _: User = Depends(manager_only)) -> dict:
    profile = db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(404, "No such profile.")
    # Permanent, and it says so on the button. What goes is this identity's own
    # record; the postings it found stay in the pool, because other profiles
    # have applied for them and their history is not this one's to delete.
    db.execute(delete(Application).where(Application.profile_id == profile.id))
    db.execute(delete(Assignment).where(Assignment.profile_id == profile.id))
    gone = select(Import.id).where(Import.profile_id == profile.id)
    db.execute(delete(ImportRow).where(ImportRow.import_id.in_(gone)))
    db.execute(delete(Import).where(Import.profile_id == profile.id))
    for job in db.scalars(select(Job).where(Job.found_by_id == profile.id)).all():
        job.found_by_id = None
    db.delete(profile)
    db.commit()
    return {"deleted": profile_id}


# --------------------------------------------------------------------------- #
# One profile's work
# --------------------------------------------------------------------------- #

def reachable(profile_id: int, db: Session, user: User) -> Profile:
    """The profile, or a 403. A BD reaches the identities they hold and no others.

    A manager reaches everything read-only — the point of their screens is the
    numbers, and a number nobody can click into is a number nobody can check.
    """
    profile = db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(404, "No such profile.")
    if user.role != "manager" and profile.user_id != user.id:
        raise HTTPException(403, "That profile is not yours.")
    return profile


@app.get("/profiles/{profile_id}/own")
def get_own(profile_id: int, db: Session = Depends(get_db),
            user: User = Depends(current_user),
            span: Window = Depends(window)) -> list[dict]:
    reachable(profile_id, db, user)
    return dispatch.own_jobs(db, profile_id, *span)


@app.post("/profiles/{profile_id}/own")
def log_own(profile_id: int, body: FindsIn, db: Session = Depends(get_db),
            user: User = Depends(current_user)) -> dict:
    """Log what this profile found and applied for.

    The reply counts the four outcomes rather than throwing on the first bad
    row, because somebody pasting thirty lines wants the twenty-eight good ones
    saved and a note about the other two.
    """
    profile = reachable(profile_id, db, user)
    if user.role == "manager" and profile.user_id != user.id:
        raise HTTPException(403, "Only the BD who holds a profile logs its work.")
    tally = {"added": 0, "known": 0, "duplicate": 0, "reapplied": 0, "unusable": 0}
    for row in body.jobs:
        line = row.model_dump()
        tally[dispatch.log_find(db, profile, line,
                                reapply=line.pop("reapply"))["status"]] += 1
    db.commit()
    return tally


@app.post("/profiles/{profile_id}/own/check")
def check_own(profile_id: int, body: FindsIn, db: Session = Depends(get_db),
              user: User = Depends(current_user)) -> dict:
    """Before filing: which of these lines has this BD applied for already?

    Nothing is written. The entry grid calls this first and, for every line
    that comes back, tells the BD where and when they applied, with an Ignore
    button that files it anyway. Lines are matched the same way filing matches
    them — by fingerprint — so "already applied" here and "duplicate" there
    can never disagree.
    """
    profile = reachable(profile_id, db, user)
    found = []
    for index, row in enumerate(body.jobs):
        hits = dispatch.earlier_applications(db, profile, row.model_dump())
        if hits:
            found.append({"index": index, "applied": hits})
    return {"matches": found}


@app.delete("/profiles/{profile_id}/own/{application_id}")
def drop_own(profile_id: int, application_id: int, db: Session = Depends(get_db),
             user: User = Depends(current_user)) -> dict:
    """Undo a mistyped find.

    If nobody else has applied for the posting it goes too, off everybody's
    list — a typo dispatched to eight profiles that cannot be withdrawn is
    worse than the typo. The moment one colleague has applied the posting is
    part of their history and stays, minus this profile's claim on it.
    """
    reachable(profile_id, db, user)
    row = db.get(Application, application_id)
    if not row or row.profile_id != profile_id:
        raise HTTPException(404, "No such entry on this profile.")
    job_id = row.job_id
    db.delete(row)
    db.flush()

    withdrawn = False
    others = db.scalar(select(func.count()).select_from(Application)
                       .where(Application.job_id == job_id))
    if not others:
        db.execute(delete(Assignment).where(Assignment.job_id == job_id))
        job = db.get(Job, job_id)
        if job:
            db.delete(job)
        withdrawn = True

    db.commit()
    return {"deleted": application_id, "job_withdrawn": withdrawn}


@app.get("/profiles/{profile_id}/others")
def get_others(profile_id: int, status: str = Query("pending"),
               db: Session = Depends(get_db), user: User = Depends(current_user),
               span: Window = Depends(window)) -> list[dict]:
    reachable(profile_id, db, user)
    if status not in ("pending", "applied", "skipped"):
        raise HTTPException(400, "Status is pending, applied or skipped.")
    return dispatch.others_jobs(db, profile_id, status, *span)


@app.post("/assignments/bulk")
def move_many(body: BulkIn, db: Session = Depends(get_db),
              user: User = Depends(current_user)) -> dict:
    """Apply for, or turn down, everything that was ticked. Reversible both ways.

    Declared above `/assignments/{assignment_id}` because FastAPI matches in
    the order routes are written, and the path parameter would otherwise
    swallow the literal and try to read "bulk" as a row id.

    The same `set_status` per row as the single button, in one transaction —
    which is the point. A BD who has just had three thousand of a colleague's
    imported finds land on their pending list is not going to press Skip three
    thousand times, and three thousand requests is not a kinder way to ask.

    Gated on the manager's `select_all` switch, on the server and not only on
    the button. A switch the browser is free to ignore is not a switch.
    """
    if body.status not in ("pending", "applied", "skipped"):
        raise HTTPException(400, "Status is pending, applied or skipped.")
    if user.role != "manager" and not settings.get(db, "select_all"):
        raise HTTPException(
            403, "Your manager has switched Select all off. Use the buttons on "
                 "each row.")

    rows = db.scalars(select(Assignment).where(Assignment.id.in_(body.ids))).all()
    # Permission is per profile, not per row: a thousand ticked rows on one
    # profile is one check, and `reachable` raises on the first one that is not
    # this BD's to touch rather than quietly doing the rest.
    for profile_id in {row.profile_id for row in rows}:
        reachable(profile_id, db, user)

    moved = 0
    for row in rows:
        if row.status == body.status and not (body.status == "skipped" and body.reason):
            continue  # already there — not a move, and not worth counting as one
        dispatch.set_status(db, row, body.status, body.applied_on, body.reason)
        moved += 1
    db.commit()
    # `missing` is honest about a stale screen: rows ticked from a list that
    # has since been re-read somewhere else simply are not there any more.
    return {"moved": moved, "unchanged": len(rows) - moved,
            "missing": len(set(body.ids)) - len(rows), "status": body.status}


@app.post("/assignments/{assignment_id}")
def move(assignment_id: int, body: StatusIn, db: Session = Depends(get_db),
         user: User = Depends(current_user)) -> dict:
    """Apply for an others' job, or turn it down. Reversible both ways."""
    row = db.get(Assignment, assignment_id)
    if not row:
        raise HTTPException(404, "No such job on any list.")
    reachable(row.profile_id, db, user)
    if body.status not in ("pending", "applied", "skipped"):
        raise HTTPException(400, "Status is pending, applied or skipped.")
    dispatch.set_status(db, row, body.status, body.applied_on, body.reason)
    db.commit()
    return {"id": row.id, "status": row.status, "skip_reason": row.skip_reason}


@app.get("/profiles/{profile_id}/all")
def get_all(profile_id: int, db: Session = Depends(get_db),
            user: User = Depends(current_user),
            span: Window = Depends(window)) -> list[dict]:
    reachable(profile_id, db, user)
    return dispatch.all_jobs(db, profile_id, *span)


@app.get("/jobs")
def every_job(db: Session = Depends(get_db), _: User = Depends(manager_only),
              span: Window = Depends(window)) -> list[dict]:
    """The pool with nobody's standing on it — the manager's all-jobs screen."""
    return dispatch.all_jobs(db, None, *span)


# --------------------------------------------------------------------------- #
# The manager's numbers
# --------------------------------------------------------------------------- #

@app.get("/overview")
def overview(db: Session = Depends(get_db), _: User = Depends(manager_only),
             span: Window = Depends(window)) -> dict:
    """Own jobs, others' jobs, skipped, applied — per profile, per BD, and total.

    Deliberately the same five words as every BD screen. A manager and a BD
    disagreeing about what "applied" counts is the failure this avoids.
    """
    counts = dispatch.profile_counts(db, *span)
    rows = db.execute(
        select(Profile, User.name).outerjoin(User, User.id == Profile.user_id)
        .order_by(Profile.name)
    ).all()

    profiles = [{**profile_out(p, holder or ""), "counts": counts.get(p.id, {})}
                for p, holder in rows]

    people: dict[int, dict] = {}
    for p, holder in rows:
        if p.user_id is None:
            continue
        seat = people.setdefault(p.user_id, {
            "user_id": p.user_id, "name": holder or "", "profiles": [],
            "own": 0, "given": 0, "from_others": 0, "skipped": 0,
            "pending": 0, "applied": 0,
        })
        seat["profiles"].append(p.name)
        for key in ("own", "given", "from_others", "skipped", "pending", "applied"):
            seat[key] += counts.get(p.id, {}).get(key, 0)

    total = {key: sum(c.get(key, 0) for c in counts.values())
             for key in ("own", "given", "from_others", "skipped", "pending", "applied")}
    # The pool counted through the same window as everything beside it.
    total["jobs"] = len(dispatch.all_jobs(db, None, *span))
    total["profiles"] = len(profiles)
    total["bds"] = db.scalar(
        select(func.count()).select_from(User).where(User.role == "bd")) or 0
    # A profile nobody holds does no work, and a manager wants to see that
    # before they wonder why the pool is moving slowly.
    total["unassigned"] = sum(1 for p in profiles if not p["user_id"])

    return {"totals": total, "profiles": profiles,
            "people": sorted(people.values(), key=lambda s: s["name"])}


# --------------------------------------------------------------------------- #
# Sheet import — three months of somebody's spreadsheet, into the pool
# --------------------------------------------------------------------------- #

@app.post("/profiles/{profile_id}/import")
async def import_sheet(profile_id: int, file: UploadFile = File(...),
                       db: Session = Depends(get_db),
                       user: User = Depends(current_user)) -> dict:
    """Upload an old sheet against this profile. Safe to repeat.

    Every line is filed as a job this profile found and applied for, which puts
    it on every other live profile's list as an others' job — the same path as
    the entry grid, because there is one pool and one way into it.

    Nothing here rejects a file for having bad lines in it. The reply counts
    all six outcomes, they add up to the number of rows read, and the ones that
    did not go in can be downloaded, fixed and sent again. Uploading the same
    sheet twice adds only what is missing.
    """
    profile = reachable(profile_id, db, user)
    if user.role == "manager" and profile.user_id != user.id:
        raise HTTPException(403, "Only the BD who holds a profile files its work.")

    data = await file.read()
    name = file.filename or "sheet.xlsx"
    before = imports.earlier_upload(db, profile.id, imports.digest_of(data))
    try:
        batch = imports.run(db, profile, user, name, data)
    except imports.SheetError as bad:
        raise HTTPException(400, str(bad))

    return {
        **imports.batch_out(batch, user.name),
        # Worth saying out loud rather than leaving somebody to wonder whether
        # they have just doubled three months of work.
        "same_file_as": before.created_at.isoformat() if before else None,
    }


@app.get("/profiles/{profile_id}/imports")
def list_imports(profile_id: int, db: Session = Depends(get_db),
                 user: User = Depends(current_user)) -> list[dict]:
    """Every sheet ever uploaded against this profile, newest first.

    Not narrowed by the date window: this is the record of what was *done to*
    the profile, and a window on when the jobs happened would hide the upload
    that put them there.
    """
    reachable(profile_id, db, user)
    return imports.history(db, profile_id)


@app.get("/imports/{import_id}/leftovers.xlsx")
def export_leftovers(import_id: int, db: Session = Depends(get_db),
                     user: User = Depends(current_user)) -> Response:
    """The lines that upload could not file, in a sheet that imports back in."""
    batch = db.get(Import, import_id)
    if not batch:
        raise HTTPException(404, "No such upload.")
    profile = reachable(batch.profile_id, db, user)
    rows = imports.leftovers(db, import_id)
    if not rows:
        raise HTTPException(404, "Every line of that sheet went in. Nothing left over.")
    content, filename = exports.leftovers_workbook(
        profile.name, imports.batch_out(batch), rows)
    return Response(content, media_type=XLSX, headers=attachment(filename))


@app.get("/import-template.xlsx")
def export_template(db: Session = Depends(get_db),
                    _: User = Depends(current_user)) -> Response:
    """The six columns an upload is read through, as a file to fill in.

    The platform dropdown's current list goes into the example line, so the
    template answers "what do I write in the platform column" with a board this
    workspace actually uses.
    """
    boards = list(db.scalars(select(Platform.name).order_by(Platform.name)).all())
    content, filename = exports.template_workbook(boards)
    return Response(content, media_type=XLSX, headers=attachment(filename))


# --------------------------------------------------------------------------- #
# The manager's switches
# --------------------------------------------------------------------------- #

@app.get("/settings")
def get_settings(db: Session = Depends(get_db),
                 _: User = Depends(current_user)) -> dict:
    """Readable by anybody signed in: a BD screen has to know what to draw."""
    return settings.all_settings(db)


@app.patch("/settings")
def edit_settings(body: SettingsIn, db: Session = Depends(get_db),
                  _: User = Depends(manager_only)) -> dict:
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            settings.put(db, key, bool(value))
    db.commit()
    return settings.all_settings(db)


# --------------------------------------------------------------------------- #
# Job platforms — the manager keeps the list, everybody types against it
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# The Google Sheet mirror
# --------------------------------------------------------------------------- #

@app.get("/sheets")
def sheet_status(db: Session = Depends(get_db),
                 _: User = Depends(manager_only)) -> dict:
    """Whether the mirror is pointed anywhere, switched on, and keeping up."""
    return sheets.status(db)


class SheetIn(BaseModel):
    """Where the two files are. Absent means leave that one as it is."""
    team_sheet: str | None = None
    manager_sheet: str | None = None


@app.put("/sheets")
def set_sheets(body: SheetIn, db: Session = Depends(get_db),
               _: User = Depends(manager_only)) -> dict:
    """Point the mirror at its spreadsheets, or at nothing.

    Stored rather than configured, so pasting a link is something a manager does
    on a Tuesday afternoon instead of a deploy. Changing the team's file clears
    every watermark with it: a new spreadsheet is an empty one, and the tabs have
    to be written from nothing or the mirror would think it had already sent
    them.
    """
    fields = body.model_dump(exclude_unset=True)
    where: dict[str, str] = {}
    for field, key in (("team_sheet", sheets.TEAM_KEY),
                       ("manager_sheet", sheets.MANAGER_KEY)):
        if fields.get(field) is not None:
            try:
                where[key] = sheets.read_sheet_id(fields[field])
            except ValueError as wrong:
                raise HTTPException(400, str(wrong)) from wrong

    team = where.get(sheets.TEAM_KEY, sheets.team_sheet_id(db))
    boss = where.get(sheets.MANAGER_KEY, sheets.manager_sheet_id(db))
    if team and team == boss:
        # They would fight: the manager's four rewrite tabs the BD pass appends
        # to, and neither would ever settle.
        raise HTTPException(409, "The team's file and the manager's file have to "
                                 "be two different spreadsheets.")

    moved = sheets.TEAM_KEY in where and where[sheets.TEAM_KEY] != sheets.team_sheet_id(db)
    for key, value in where.items():
        settings.raw_put(db, key, value)
    db.commit()
    if moved:
        sheets.forget(db)
    return sheets.status(db)


@app.post("/sheets/sync")
def sheet_sync_now(rebuild: bool = Query(False, description="write the tabs again"),
                   target: str | None = Query(None, description="one profile only"),
                   db: Session = Depends(get_db),
                   _: User = Depends(manager_only)) -> dict:
    """Run a pass now rather than waiting for the timer.

    Both files, or one profile's tab with `target` — "profile:<id>". One tab failing does
    not stop the others; what comes back says which ones went and which did not,
    so a 200 here is not a promise that everything was written.

    A plain `def` and not `async def`, so FastAPI runs it in its threadpool: the
    Sheets client blocks, and blocking the event loop would hold up every other
    request for as long as Google takes to answer.
    """
    if not sheets.credentials():
        raise HTTPException(400, "No service account — set MBS_GOOGLE_CREDENTIALS")
    if not sheets.configured(db):
        raise HTTPException(400, "No spreadsheet yet — paste a Google Sheet link "
                                 "on the People screen")
    if not settings.get(db, "sheet_sync"):
        raise HTTPException(400, "The Google Sheet mirror is switched off")

    done = sheets.one_pass(derived=True, rebuild=rebuild, only=target) or []
    if target and not done:
        raise HTTPException(404, "No profile by that id.")
    return {"tabs": done, "failed": [one["name"] for one in done
                                     if one.get("error")]}


@app.post("/sheets/reset")
def sheet_reset(db: Session = Depends(get_db),
                _: User = Depends(manager_only)) -> dict:
    """Empty both spreadsheets and write every tab again from nothing.

    Destructive on the Google side and nowhere else: it takes out every tab in
    both files, MBS's and anybody else's, then rebuilds the ones MBS owns. The
    workspace itself is not touched — this is a mirror, and a mirror can always
    be made again from what it reflects.
    """
    if not sheets.configured(db):
        raise HTTPException(400, "Nothing to reset — no spreadsheet, or no "
                                 "service account")
    books = [sheets.open_book(where) for where in
             (sheets.team_sheet_id(db), sheets.manager_sheet_id(db)) if where]
    removed: list[str] = []
    try:
        for book in books:
            removed += sheets.reset(db, book)
    except Exception as problem:                    # noqa: BLE001
        raise HTTPException(502, f"Google refused: {problem}") from problem

    sheets.forget(db)
    done = sheets.one_pass(derived=True, rebuild=True) or []
    # The blank tabs only existed to keep a file from having none at all.
    for book in books:
        sheets.drop_placeholder(book)
    return {"removed": removed, "tabs": done,
            "failed": [one["name"] for one in done if one.get("error")]}


@app.get("/platforms")
def list_platforms(db: Session = Depends(get_db),
                   _: User = Depends(current_user)) -> list[dict]:
    """Readable by anybody signed in: it fills the entry grid dropdown."""
    rows = db.scalars(select(Platform).order_by(Platform.name)).all()
    return [{"id": p.id, "name": p.name} for p in rows]


@app.post("/platforms", status_code=201)
def add_platform(body: PlatformIn, db: Session = Depends(get_db),
                 _: User = Depends(manager_only)) -> dict:
    name = body.name.strip()
    if db.scalar(select(Platform).where(func.lower(Platform.name) == name.lower())):
        raise HTTPException(409, "That platform is already on the list.")
    row = Platform(name=name)
    db.add(row)
    db.commit()
    return {"id": row.id, "name": row.name}


@app.delete("/platforms/{platform_id}")
def remove_platform(platform_id: int, db: Session = Depends(get_db),
                    _: User = Depends(manager_only)) -> dict:
    """Takes it off the dropdown. Jobs already recorded against it keep it.

    A job stores its platform as the text that was chosen, not a reference to
    this row, so nothing recorded last month changes because a board was
    retired today.
    """
    row = db.get(Platform, platform_id)
    if not row:
        raise HTTPException(404, "No such platform.")
    still_used = db.scalar(select(func.count()).select_from(Job)
                           .where(func.lower(Job.platform) == row.name.lower())) or 0
    db.delete(row)
    db.commit()
    return {"deleted": platform_id, "jobs_keeping_it": still_used}


# --------------------------------------------------------------------------- #
# Exports
# --------------------------------------------------------------------------- #

@app.get("/profiles/{profile_id}/export.xlsx")
def export_profile(profile_id: int, db: Session = Depends(get_db),
                   user: User = Depends(current_user),
                   span: Window = Depends(window)) -> Response:
    """One profile's three lists and its counts, as a workbook.

    Read through the same date window as the screens, so what comes out of the
    file and what was on the screen it was exported from are the same numbers.
    """
    profile = reachable(profile_id, db, user)
    content, filename = exports.profile_workbook(db, profile, *span)
    return Response(content, media_type=XLSX, headers=attachment(filename))


@app.get("/export.xlsx")
def export_workspace(db: Session = Depends(get_db),
                     manager: User = Depends(manager_only),
                     span: Window = Depends(window)) -> Response:
    """The whole workspace: totals, by BD, by profile, the pool, and the people."""
    board = overview(db=db, _=manager, span=span)
    people = list_users(db=db, _=manager)
    content, filename = exports.workspace_workbook(db, board, people, *span)
    return Response(content, media_type=XLSX, headers=attachment(filename))


@app.get("/health")
def health() -> dict:
    return {"ok": True, "app": "MBS"}
