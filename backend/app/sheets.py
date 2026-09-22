"""Two spreadsheets, mirrored from MBS without anybody pressing a button.

A BD applies for a job and it is on their tab about five seconds later. That is
the whole point of this module, and it goes **one way**. A row in a spreadsheet
has no fingerprint and no id, so a sheet that could be edited back into the pool
would be a workspace that disagrees with itself; the ways in stay the entry grid
and the sheet importer, which both go through `log_find` and both dedupe.

**The team's file** has a tab per BD, named after them, carrying everything that
person has applied for across every profile they run — their own finds and the
others' jobs they took on, which is exactly the "applied" of the five words. A
BD hired this afternoon has a tab on the next pass and fills it as they work;
nobody configures anything.

**The manager's file** is separate, and holds the four screens they read. Two
files rather than four tabs in one, because the two are shown to different
people: a BD opening the team's file should not have to scroll past the whole
workspace's totals to find their own name, and a manager's numbers are not
something every BD needs a link to.

Tabs are appended to, never rewritten, except the manager's — those are answers
rather than events, and a count that went down cannot be appended.

**Why appending needs watching.** Undoing an others' job deletes its
application, and a tab that only ever appends cannot take a row back. So every
pass asks the database two things about the rows it believes are up there — how
many there are, and when the newest of them was filed — and writes the tab again
from scratch when either has moved. One query, cheap enough to do every time, and
the rare thing (an undo) pays for itself instead of every cycle paying for it.
See `_fingerprint` for why the stamp is there as well as the count. A slower
unconditional rebuild sits behind all of it as the backstop for anything odder,
such as a process killed between the rows landing in Google and the watermark
being committed here.

The manager's rows come from `exports.py`, the same functions the .xlsx
workbooks are built from. A row means one thing, or the manager reading the
sheet and the manager reading the file are looking at two different workspaces.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select, true
from sqlalchemy.orm import Session, aliased

from . import dispatch, exports, settings
from .db import SessionLocal
from .models import Application, Job, Profile, User, utcnow

log = logging.getLogger("mbs.sheets")

# Bookkeeping, kept in the settings table next to the switches. None of these is
# in settings.DEFAULTS, so none is offered to the manager as something to set.
# Each is suffixed with a target's key — one tab's watermark says nothing about
# another's.
WATERMARK = "sheet_sync_watermark"   # the highest application id on the tab
LOGGED = "sheet_sync_logged"         # how many rows were appended to it
LAST_FILED = "sheet_sync_last_filed"  # the newest `created_at` among those rows
TAB_NAME = "sheet_sync_tab"          # the tab it was written to, to catch renames

# Where the two spreadsheets are. Stored values so a manager can paste a link
# without a deploy; the environment is the fallback, for a server that would
# rather be told once at boot.
TEAM_KEY = "sheet_id"
MANAGER_KEY = "manager_sheet_id"

# Google will not let a spreadsheet have no tabs at all, so emptying one has to
# leave something behind. This is that something, and it is taken out again the
# moment the real tabs exist.
PLACEHOLDER = "MBS"

# The manager's four, in their own file, so they need no prefix to stay clear of
# anybody's name.
OVERVIEW_TAB = "Overview"
BD_TAB = "By BD"
PROFILES_TAB = "By profile"
DAY_TAB = "By day"
POOL_TAB = "All jobs"
MANAGER_TABS = (OVERVIEW_TAB, BD_TAB, PROFILES_TAB, DAY_TAB, POOL_TAB)

# What a BD's tab carries: everything they have applied for, in the order the
# work happened. "Profile" is there because one person may run several and a
# client cannot be told which identity applied from the company name alone;
# "Own or others" is the split every number on the manager's screen is made of.
APPLIED_COLUMNS = ["Applied on", "Profile", "Company name", "Job title",
                   "Job link", "Job platform", "Email", "Own or others",
                   "Found by", "Filed at"]

# Sheets allows 60 write requests a minute per user, so a run that filed three
# thousand lines must not become three thousand calls. Rows go up in chunks of
# this many, which puts that import at two.
CHUNK = 2000

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


# --------------------------------------------------------------------------- #
# What it is pointed at
# --------------------------------------------------------------------------- #

def team_sheet_id(db: Session) -> str:
    """The file with a tab per BD."""
    return (settings.raw_get(db, TEAM_KEY, "").strip()
            or os.environ.get("MBS_SHEET_ID", "").strip())


def manager_sheet_id(db: Session) -> str:
    """The file with the manager's four screens."""
    return (settings.raw_get(db, MANAGER_KEY, "").strip()
            or os.environ.get("MBS_MANAGER_SHEET_ID", "").strip())


def credentials() -> str:
    """The service account: a path to its JSON key, or the JSON itself.

    Both spellings, because the two places this runs want different ones. A
    server has a file; a platform that only offers environment variables has to
    be handed the whole document. One account covers both spreadsheets — share
    each with the same address.
    """
    return os.environ.get("MBS_GOOGLE_CREDENTIALS", "").strip()


def read_sheet_id(typed: str) -> str:
    """The spreadsheet id out of whatever somebody pasted.

    Nobody has the bare id to hand — what is in their clipboard is the address
    bar. Both are taken, and anything that is neither is refused rather than
    stored, because a sheet id that is wrong fails later, once, in a log.
    """
    text = (typed or "").strip()
    if not text:
        return ""
    found = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", text)
    if found:
        return found.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{8,120}", text):
        return text
    raise ValueError("That is not a Google Sheet link or id.")


def link(where: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{where}" if where else ""


def _seconds(name: str, fallback: float) -> float:
    try:
        return max(5.0, float(os.environ.get(name, "") or fallback))
    except ValueError:
        return fallback


def configured(db: Session) -> bool:
    """Whether there is anything to sync to, and anything to sync with.

    Either file on its own is enough: a team that wants the BD tabs and no
    manager file, or the other way round, is a workspace that mirrors.
    """
    return bool(credentials()
                and (team_sheet_id(db) or manager_sheet_id(db)))


# --------------------------------------------------------------------------- #
# A tab per BD
# --------------------------------------------------------------------------- #

# Google refuses these in a tab name, and caps it at 100 characters.
_BANNED = re.compile(r"[:\\/?*\[\]]+")


def tab_name(name: str) -> str:
    """Somebody's name, as a tab Google will accept."""
    clean = _BANNED.sub(" ", name or "").strip()
    clean = re.sub(r"\s+", " ", clean)
    return clean[:99] or "Unnamed"


@dataclass(frozen=True)
class Target:
    """One BD and the tab their applied jobs go on."""
    key: str
    tab: str
    user_id: int
    name: str


def targets(db: Session) -> list[Target]:
    """Every BD, in name order, plus anybody else who holds a profile.

    The second half is not pedantry: a manager who runs a profile of their own
    is doing the work, and a tab list that only looked at the role would drop
    what they applied for without saying so.
    """
    holders = select(Profile.user_id).where(Profile.user_id.is_not(None))
    rows = db.execute(
        select(User.id, User.name)
        .where(or_(User.role == "bd", User.id.in_(holders)))
        .order_by(User.name)).all()
    return [Target(f"bd:{uid}", tab_name(name), uid, name) for uid, name in rows]


# --------------------------------------------------------------------------- #
# The Sheets API, reduced to the six things this module does
# --------------------------------------------------------------------------- #

class GoogleWorkbook:
    """One spreadsheet, as an object with six methods.

    The Google libraries are imported in here rather than at the top of the
    file, so a workspace with the mirror switched off does not need them
    installed to boot.
    """

    def __init__(self, spreadsheet_id: str, source: str) -> None:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        if source.lstrip().startswith("{"):
            info = json.loads(source)
        else:
            with open(source, encoding="utf-8") as handle:
                info = json.load(handle)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        # cache_discovery off: it writes a cache to a directory that is often
        # not writable, and warns on every boot when it is not.
        self._api = build("sheets", "v4", credentials=creds,
                          cache_discovery=False).spreadsheets()
        self._id = spreadsheet_id

    def tabs(self) -> dict[str, int]:
        """Every tab in the file, name to Google's id for it."""
        meta = self._api.get(spreadsheetId=self._id,
                             fields="sheets.properties(sheetId,title)").execute()
        return {page["properties"]["title"]: page["properties"]["sheetId"]
                for page in meta.get("sheets", [])}

    def add_tabs(self, names: list[str]) -> None:
        if not names:
            return
        self._api.batchUpdate(spreadsheetId=self._id, body={"requests": [
            {"addSheet": {"properties": {"title": name}}} for name in names]
        }).execute()

    def rename_tab(self, tab_id: int, name: str) -> None:
        self._api.batchUpdate(spreadsheetId=self._id, body={"requests": [
            {"updateSheetProperties": {
                "properties": {"sheetId": tab_id, "title": name},
                "fields": "title"}}]}).execute()

    def delete_tabs(self, tab_ids: list[int]) -> None:
        if not tab_ids:
            return
        self._api.batchUpdate(spreadsheetId=self._id, body={"requests": [
            {"deleteSheet": {"sheetId": one}} for one in tab_ids]}).execute()

    def clear(self, tab: str) -> None:
        self._api.values().clear(spreadsheetId=self._id,
                                 range=f"'{tab}'", body={}).execute()

    def append(self, tab: str, rows: list[list]) -> None:
        # RAW, not USER_ENTERED. A company called "=Dyson" or a title starting
        # with a + is a string, and letting Sheets read it as a formula would
        # both lose the row and hand anybody who can log a find a way to put a
        # formula in the manager's spreadsheet. The cost is that the link is
        # text rather than a hyperlink object; Sheets makes a bare URL clickable
        # anyway, and the .xlsx export is the one that promises a real one.
        for start in range(0, len(rows), CHUNK):
            self._api.values().append(
                spreadsheetId=self._id, range=f"'{tab}'!A1",
                valueInputOption="RAW", insertDataOption="INSERT_ROWS",
                body={"values": rows[start:start + CHUNK]}).execute()


def open_book(spreadsheet_id: str) -> GoogleWorkbook:
    return GoogleWorkbook(spreadsheet_id, credentials())


# --------------------------------------------------------------------------- #
# The rows
# --------------------------------------------------------------------------- #

def _visible(db: Session):
    """Which applications belong on a tab, as a WHERE clause.

    An uploaded sheet is in or out as one decision, and it is the manager's.
    Off — the default — the mirror carries what the team is finding now: a line
    somebody typed into the entry grid, and nothing else. On, three months of
    imported history goes up with it.

    Every reader below goes through this, `_fingerprint` included. If the rows
    that get sent and the rows that get counted ever disagreed, the drift check
    would find a difference it could not fix and rebuild the tab on every pass,
    for ever.
    """
    if settings.get(db, "sheet_sync_imports"):
        return true()
    return Application.import_id.is_(None)


def applied_rows(db: Session, target: Target,
                 after: int = 0) -> tuple[list[list], int]:
    """What this BD has applied for since id `after`, and the new watermark.

    Every profile they hold, together. Applications and nothing else, which is
    the five words' "applied": their own finds, plus the others' jobs they took
    on. A pending row is not on here because nobody has applied for it yet, and
    a skipped one never will be.

    Ordered by id rather than by date, because the tab is a log of the order the
    work was filed in, and the date column is free text somebody backfilling
    yesterday types into.
    """
    finder = aliased(Profile)
    found = db.execute(
        select(Application, Job, Profile.name, finder.name)
        .join(Job, Job.id == Application.job_id)
        .join(Profile, Profile.id == Application.profile_id)
        .outerjoin(finder, finder.id == Job.found_by_id)
        .where(Application.id > after, _visible(db),
               Profile.user_id == target.user_id)
        .order_by(Application.id)
    ).all()

    rows: list[list] = []
    mark = after
    for application, job, under, found_by in found:
        filed: datetime | None = application.created_at
        rows.append([
            application.applied_on or (filed.date().isoformat() if filed else ""),
            under, job.company, job.title, job.url, job.platform,
            application.email,
            "Own job" if application.source == "own" else "Others job",
            found_by or "—",
            filed.isoformat(sep=" ", timespec="seconds") if filed else "",
        ])
        mark = max(mark, application.id)
    return rows, mark


def board(db: Session) -> dict:
    """The manager's overview, all time — the shape `exports` wants.

    Built here rather than borrowed from the route, because the route is a
    request with a signed-in user on it and this runs on a timer with nobody
    signed in at all. All time and not a window: a mirror with a date range
    baked into it is a sheet that quietly stops growing.
    """
    counts = dispatch.profile_counts(db, None, None)
    rows = db.execute(
        select(Profile, User.name).outerjoin(User, User.id == Profile.user_id)
        .order_by(Profile.name)
    ).all()

    profiles = [{"name": p.name, "headline": p.headline, "bd": holder or "",
                 "is_active": p.is_active, "user_id": p.user_id,
                 "counts": counts.get(p.id, {})} for p, holder in rows]

    keys = ("own", "given", "from_others", "skipped", "pending", "applied")
    people: dict[int, dict] = {}
    for p, holder in rows:
        if p.user_id is None:
            continue
        seat = people.setdefault(p.user_id, {
            "user_id": p.user_id, "name": holder or "", "profiles": [],
            **{key: 0 for key in keys}})
        seat["profiles"].append(p.name)
        for key in keys:
            seat[key] += counts.get(p.id, {}).get(key, 0)

    totals = {key: sum(c.get(key, 0) for c in counts.values()) for key in keys}
    # `/overview` counts this as the length of all_jobs through its window. With
    # no window those are the same number by construction, and a COUNT does not
    # build every row of the pool to find out how many there are.
    totals["jobs"] = db.scalar(select(func.count()).select_from(Job)) or 0
    totals["profiles"] = len(profiles)
    totals["bds"] = db.scalar(
        select(func.count()).select_from(User).where(User.role == "bd")) or 0
    totals["unassigned"] = sum(1 for p in profiles if not p["user_id"])
    return {"totals": totals, "profiles": profiles,
            "people": sorted(people.values(), key=lambda s: s["name"])}


# --------------------------------------------------------------------------- #
# One pass
# --------------------------------------------------------------------------- #

def _book(key: str, target: Target) -> str:
    """Where one target's bookkeeping is filed."""
    return f"{key}:{target.key}"


def _fingerprint(db: Session, target: Target, mark: int) -> tuple[int, str]:
    """This BD's applications at or below `mark`: how many, and the newest.

    Two numbers rather than one, and the second is the interesting one. SQLite
    hands back the highest rowid it has just freed, so deleting the newest
    application and filing another one between two passes can produce a row with
    the same id as the one that went — leaving the count identical and the new
    row invisible to anything watching ids alone. Its `created_at` is later,
    which is what gives it away. Postgres sequences never reuse, so there the
    stamp is belt to the count's braces.
    """
    count, newest = db.execute(
        select(func.count(), func.max(Application.created_at))
        .join(Profile, Profile.id == Application.profile_id)
        .where(Application.id <= mark, _visible(db),
               Profile.user_id == target.user_id)).one()
    return count or 0, newest.isoformat() if newest else ""


def drifted(db: Session, target: Target, mark: int, logged: int,
            filed: str) -> bool:
    """Whether the tab still says what this BD's applications say.

    An application that was put on the tab and is not in the database any more
    means somebody pressed Undo, or withdrew a mistyped find — or a profile was
    handed to somebody else, which takes its history with it. One query, not a
    read of the whole spreadsheet back out of Google.
    """
    count, newest = _fingerprint(db, target, mark)
    return count != logged or newest != filed


def place_tab(db: Session, book, tabs: dict[str, int], target: Target) -> bool:
    """Make sure this BD's tab exists, and say whether it is ours yet.

    Returns "has this tab never been written by us", not "did we just make it" —
    and the difference matters. A tab somebody created by hand, or one another
    writer made a moment ago, exists and is empty; appending into it would leave
    a column of data with no headings above it. Whether we have written a tab is
    something we know from our own bookkeeping, without asking Google.

    Somebody renamed on the People screen keeps their tab and its history: the
    alternative is a second tab with the same rows on it and no way to tell
    which is live. A tab of ours that somebody deleted is made again, and made
    again means written from nothing.

    `tabs` is a snapshot taken once for the whole pass, and a snapshot can be
    wrong: another process writing the same spreadsheet may have made the tab
    since it was read. Google says so rather than quietly succeeding, so the
    answer is to look again and carry on — creating a tab is the one thing here
    that two writers can genuinely collide over.
    """
    had = settings.raw_get(db, _book(TAB_NAME, target), "")
    made = False

    if target.tab not in tabs:
        if had and had in tabs:
            book.rename_tab(tabs[had], target.tab)
            tabs[target.tab] = tabs.pop(had)
        else:
            try:
                book.add_tabs([target.tab])
            except Exception as problem:            # noqa: BLE001
                if "already exists" not in str(problem):
                    raise
                tabs.update(book.tabs())
            else:
                # Google's id for it is not needed until a reset, which reads
                # the tab list again anyway.
                tabs[target.tab] = -1
                made = True

    return made or not had


def sync_bd(db: Session, book, tabs: dict[str, int], target: Target, *,
            rebuild: bool = False) -> dict:
    """One pass over one BD's tab.

    The tab is written before the watermark is committed, never the other way
    round: a crash in between repeats rows, which the next rebuild puts right,
    while the other order loses them for good.
    """
    fresh = place_tab(db, book, tabs, target)
    mark = int(settings.raw_get(db, _book(WATERMARK, target), "0") or 0)
    logged = int(settings.raw_get(db, _book(LOGGED, target), "0") or 0)
    filed = settings.raw_get(db, _book(LAST_FILED, target), "")

    from_scratch = rebuild or fresh or drifted(db, target, mark, logged, filed)

    if from_scratch:
        rows, mark = applied_rows(db, target, 0)
        book.clear(target.tab)
        book.append(target.tab, [APPLIED_COLUMNS] + rows)
        logged, appended = len(rows), 0
    else:
        rows, mark = applied_rows(db, target, mark)
        if rows:
            book.append(target.tab, rows)
        logged += len(rows)
        appended = len(rows)
    filed = _fingerprint(db, target, mark)[1]

    settings.raw_put(db, _book(WATERMARK, target), str(mark))
    settings.raw_put(db, _book(LOGGED, target), str(logged))
    settings.raw_put(db, _book(LAST_FILED, target), filed)
    settings.raw_put(db, _book(TAB_NAME, target), target.tab)
    db.commit()

    return {"target": target.key, "name": target.name, "tab": target.tab,
            "appended": appended, "rebuilt": from_scratch, "rows": logged,
            "watermark": mark, "new_tab": fresh}


def _titled(lines: list[tuple[str, object]], title: str) -> list[list]:
    """A summary as two columns, the way a spreadsheet wants it."""
    return [[title, ""]] + [["" if label is None else label,
                             "" if value is None else value]
                            for label, value in lines]


def rewrite_manager(db: Session, book, tabs: dict[str, int]) -> None:
    """The manager's file: four tabs that are answers rather than events.

    Exactly what the manager's screens show, out of the same functions in
    `exports.py` that build the .xlsx — so the sheet, the export and the screen
    are three views of one set of numbers, never three sets.
    """
    book.add_tabs([tab for tab in MANAGER_TABS if tab not in tabs])
    for tab in MANAGER_TABS:
        tabs.setdefault(tab, -1)

    view = board(db)
    totals = view["totals"]

    # The stamp is not decoration. A mirror that is quietly three days stale
    # looks exactly like one that is up to date, and the only person who can
    # tell is the one who put the time on it.
    book.clear(OVERVIEW_TAB)
    book.append(OVERVIEW_TAB, _titled(
        [("Last written", utcnow().isoformat(sep=" ", timespec="seconds") + " UTC"),
         (None, None)]
        + exports.workspace_summary(view, None, None)
        + [(None, None),
           ("Others' jobs dealt with %",
            exports.percent(totals["given"] - totals["pending"], totals["given"])),
           ("Own jobs as a share of applied %",
            exports.percent(totals["own"], totals["applied"])),
           ("Applications per BD",
            round(totals["applied"] / totals["bds"]) if totals["bds"] else "")],
        "MBS — the whole workspace"))

    for tab, (columns, rows) in (
            (BD_TAB, exports.bd_table(view)),
            (PROFILES_TAB, exports.profile_table(view)),
            (DAY_TAB, exports.by_day_table(db, None, None)),
            (POOL_TAB, exports.pool_table(db, None, None))):
        book.clear(tab)
        book.append(tab, [columns] + rows)


# --------------------------------------------------------------------------- #
# Every tab, one pass
# --------------------------------------------------------------------------- #

# What /sheets reports, one entry per BD. A mirror nobody can see the state of
# is a mirror somebody has to open the spreadsheet to trust.
running = False
state: dict[str, dict] = {}

# One pass at a time. The timer runs in a thread of its own and the manual
# routes run in FastAPI's threadpool, so without this a Sync now pressed while
# the timer is mid-pass has two writers holding two snapshots of the same tab
# list — and the second one to create a tab is told it already exists.
_one_at_a_time = threading.Lock()


def _blank() -> dict:
    return {"last_run": None, "last_error": None, "passes": 0, "rows": 0}


def reset(db: Session, book) -> list[str]:
    """Empty one spreadsheet. The caller writes it again.

    Google will not let a file have no tabs at all, so a blank one is put in
    first; `drop_placeholder` takes it out once the real tabs are back.
    """
    with _one_at_a_time:
        tabs = book.tabs()
        if PLACEHOLDER not in tabs:
            book.add_tabs([PLACEHOLDER])
        book.delete_tabs([tab_id for name, tab_id in tabs.items()
                          if name != PLACEHOLDER])
    return [name for name in tabs if name != PLACEHOLDER]


def forget(db: Session) -> None:
    """Drop every watermark, so the next pass writes each tab from nothing."""
    for target in targets(db):
        for key in (WATERMARK, LOGGED, LAST_FILED, TAB_NAME):
            settings.raw_put(db, _book(key, target), "")
    db.commit()
    state.clear()


def drop_placeholder(book) -> bool:
    """Take the blank tab out, now that there is something else in the file.

    Left alone if it is all there is: an empty spreadsheet is better than a
    refused request, and the next pass will make the real tabs and clear it.
    """
    with _one_at_a_time:
        tabs = book.tabs()
        if PLACEHOLDER not in tabs or len(tabs) < 2:
            return False
        book.delete_tabs([tabs[PLACEHOLDER]])
    return True


def one_pass(derived: bool, rebuild: bool,
             only: str | None = None) -> list[dict] | None:
    """A pass over both files, or None if the manager has it switched off.

    Each BD is written in its own try: one tab failing must not stop the ones
    after it, nor the manager's file. What comes back is one result per BD, with
    whatever went wrong recorded against the person it went wrong for.

    Each file's tab list is read once for the whole pass rather than once per
    BD. With a tab each and a pass every five seconds, the other way would spend
    the read quota finding out what it already knew.

    Blocking, on purpose — the caller either runs it in a thread or is a
    request that wanted to wait for it, and it waits its turn behind any pass
    already running.
    """
    with _one_at_a_time, SessionLocal() as db:
        if not settings.get(db, "sheet_sync") or not configured(db):
            return None

        done: list[dict] = []
        team = team_sheet_id(db)
        if team:
            book = open_book(team)
            tabs = book.tabs()
            for target in [t for t in targets(db)
                           if only is None or t.key == only]:
                here = state.setdefault(target.key, _blank())
                try:
                    result = sync_bd(db, book, tabs, target, rebuild=rebuild)
                except Exception as problem:        # noqa: BLE001
                    here["last_error"] = f"{type(problem).__name__}: {problem}"
                    log.warning("sheet mirror failed for %s: %s",
                                target.name, problem)
                    done.append({"target": target.key, "name": target.name,
                                 "error": here["last_error"]})
                    continue
                here["rows"] = result["rows"]
                here["passes"] += 1
                here["last_run"] = utcnow().isoformat(timespec="seconds")
                here["last_error"] = None
                done.append(result)

        boss = manager_sheet_id(db)
        if boss and derived and only is None:
            try:
                book = open_book(boss)
                rewrite_manager(db, book, book.tabs())
                done.append({"target": "manager", "name": "the manager's file",
                             "tab": ", ".join(MANAGER_TABS), "rebuilt": True,
                             "appended": 0, "rows": 0})
            except Exception as problem:            # noqa: BLE001
                log.warning("sheet mirror failed on the manager's file: %s",
                            problem)
                done.append({"target": "manager", "name": "the manager's file",
                             "error": f"{type(problem).__name__}: {problem}"})

        # Somebody who has been deleted stops being a target, and the state they
        # left behind would otherwise be reported for ever.
        if only is None:
            live = {t.key for t in targets(db)}
            for gone in [k for k in state if k not in live]:
                del state[gone]
    return done


async def run() -> None:
    """Append often, rewrite the manager's file less often, rebuild rarely.

    Three intervals rather than one, because the three cost different amounts.
    An append is a handful of rows; rewriting the pool is every job there is;
    rebuilding every tab is every application there has ever been, which is the
    backstop and not the job.
    """
    global running
    every = _seconds("MBS_SHEET_INTERVAL", 5)
    rewrite_every = _seconds("MBS_SHEET_REWRITE", 300)
    rebuild_every = _seconds("MBS_SHEET_REBUILD", 3600)

    running = True
    log.info("sheet mirror: every %ss, manager file every %ss, rebuild every %ss",
             every, rewrite_every, rebuild_every)
    since_rewrite = since_rebuild = 0.0
    try:
        while True:
            await asyncio.sleep(every)
            since_rewrite += every
            since_rebuild += every
            derived = since_rewrite >= rewrite_every
            rebuild = since_rebuild >= rebuild_every
            try:
                await asyncio.to_thread(one_pass, derived, rebuild)
            except Exception as problem:            # noqa: BLE001
                # A pass that throws must not take the loop with it: the sheet
                # being unreachable for ten minutes is not a reason for MBS to
                # stop mirroring for the rest of the day. Per-BD failures are
                # already caught inside `one_pass`; this is the database being
                # unreachable, or something else outside any one tab.
                log.warning("sheet mirror pass failed: %s", problem)
            if derived:
                since_rewrite = 0.0
            if rebuild:
                since_rebuild = 0.0
    except asyncio.CancelledError:
        raise
    finally:
        running = False


def status(db: Session) -> dict:
    """Everything a manager needs to know without opening either spreadsheet."""
    return {
        "configured": configured(db),
        "on": settings.get(db, "sheet_sync"),
        "credentials": bool(credentials()),
        "running": running,
        "team_sheet": team_sheet_id(db),
        "team_url": link(team_sheet_id(db)),
        "manager_sheet": manager_sheet_id(db),
        "manager_url": link(manager_sheet_id(db)),
        "manager_tabs": list(MANAGER_TABS),
        "bds": [{"target": t.key, "name": t.name, "tab": t.tab,
                 "user_id": t.user_id, **state.get(t.key, _blank())}
                for t in targets(db)],
    }
