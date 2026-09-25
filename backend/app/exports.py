"""Workbooks. What is on a screen, as a file somebody can send on.

Two of them are what a screen hands you: one profile's three lists for a BD,
and the whole workspace for a manager. Both carry a Summary sheet first,
because the counts are the thing anybody opening this actually wants, and both
are built through the same date window as the screen they were exported from —
an export that quietly ignored the range would be a different set of numbers
under the same heading.

Two more belong to the sheet importer at the other end of the same door: the
template that says what a sheet should look like, and the leftovers file that
hands back the lines an upload could not file, in a shape that imports.

openpyxl only. No pandas: this writes rows it already has in memory, and a
dataframe in the middle would be a dependency and a copy for nothing.
"""
from __future__ import annotations

import io
import re
from datetime import date, timedelta

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import dispatch
from .models import Application, Profile, User

HEADER_FILL = PatternFill("solid", start_color="FFEEF0FD")
HEADER_FONT = Font(bold=True, color="FF3F45AD")
TITLE_FONT = Font(bold=True, size=13)
LINK_FONT = Font(color="FF3F45AD", underline="single")

# Wide enough to read, narrow enough that a link does not push every other
# column off the page. A URL column gets its own, tighter, cap.
MAX_WIDTH = 46
URL_WIDTH = 52


def _sheet(book: Workbook, name: str, columns: list[str], rows: list[list],
           url_column: str | None = "Job link") -> None:
    """One sheet: a bold frozen header, the rows, and sensible widths."""
    page = book.create_sheet(name[:31])
    page.append(columns)
    for cell in page[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center")
    page.freeze_panes = "A2"
    page.auto_filter.ref = None  # set below, once the height is known

    link_at = columns.index(url_column) + 1 if url_column in columns else None

    for row in rows:
        page.append(["" if value is None else value for value in row])

    if link_at:
        # A real hyperlink, so the cell is clickable rather than just blue text.
        for index in range(2, page.max_row + 1):
            cell = page.cell(row=index, column=link_at)
            if isinstance(cell.value, str) and cell.value.startswith("http"):
                cell.hyperlink = cell.value
                cell.font = LINK_FONT

    if page.max_row > 1:
        page.auto_filter.ref = (
            f"A1:{get_column_letter(len(columns))}{page.max_row}")

    for index, column in enumerate(columns, start=1):
        longest = max([len(str(column))]
                      + [len(str(row[index - 1])) for row in rows
                         if index - 1 < len(row) and row[index - 1] is not None] or [0])
        cap = URL_WIDTH if index == link_at else MAX_WIDTH
        page.column_dimensions[get_column_letter(index)].width = min(longest + 3, cap)


def _summary(book: Workbook, title: str, lines: list[tuple[str, object]]) -> None:
    """The first sheet: what this file is, then the numbers, one per row."""
    page = book.create_sheet("Summary")
    page["A1"] = title
    page["A1"].font = TITLE_FONT
    page.append([])
    for label, value in lines:
        page.append(["" if label is None else label, value])
    # Only ever assign a font, never read one back and write it again:
    # `cell.font` hands out a proxy that openpyxl refuses to store.
    for cell in page["A"]:
        if cell.row > 2 and cell.value:
            cell.font = Font(bold=True)
    page.column_dimensions["A"].width = 32
    page.column_dimensions["B"].width = 46


def _window_line(since: date | None, until: date | None) -> str:
    if not since and not until:
        return "All time"
    if since and until:
        return f"{since} to {until}"
    return f"from {since}" if since else f"up to {until}"


def _bytes(book: Workbook) -> bytes:
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def safe_filename(name: str) -> str:
    """Something every operating system will accept as a filename."""
    clean = re.sub(r"[\\/:*?\"<>|]+", " ", name)
    return re.sub(r"\s+", " ", clean).strip()


# --------------------------------------------------------------------------- #
# One profile — what a BD exports
# --------------------------------------------------------------------------- #

OWN_COLUMNS = ["Company name", "Job title", "Job link", "Job platform",
               "Email", "Date", "Also applied"]
OTHERS_COLUMNS = ["Company name", "Job title", "Job link", "Job platform",
                  "Found by", "Status", "Already applied", "Skip reason"]
ALL_COLUMNS = ["Company name", "Job title", "Job link", "Job platform",
               "Found by", "Applications", "Applied by", "This profile",
               "First seen"]

STANDING = {"own": "Own job", "applied": "Applied", "skipped": "Skipped",
            "pending": "Pending", "none": "—"}


# Pulled out of the workbook, like the workspace tables further down, so the
# Google Sheet mirror sends the same rows to a profile's own spreadsheet that
# the Export button puts in its .xlsx. See sheets.py.

def profile_summary(db: Session, profile: Profile, since: date | None,
                    until: date | None) -> list[tuple[str, object]]:
    """This profile's five counts, and who is running it."""
    counts = dispatch.profile_counts(db, since, until).get(profile.id, {})
    holder = db.scalar(select(User.name).where(User.id == profile.user_id)) or "nobody"
    return [
        ("Headline", profile.headline or "—"),
        ("Platform", profile.platform or "—"),
        ("Run by", holder),
        ("Date range", _window_line(since, until)),
        (None, None),
        ("Own jobs", counts.get("own", 0)),
        ("Others' jobs given", counts.get("given", 0)),
        ("Others' jobs applied for", counts.get("from_others", 0)),
        ("Skipped", counts.get("skipped", 0)),
        ("Pending", counts.get("pending", 0)),
        ("Applied in all", counts.get("applied", 0)),
    ]


def own_table(db: Session, profile_id: int, since: date | None,
              until: date | None) -> tuple[list[str], list[list]]:
    """What this profile went out and found."""
    return OWN_COLUMNS, [
        [job["company"], job["title"], job["url"], job["platform"], job["email"],
         job["applied_on"] or (job["logged_at"] or "")[:10],
         ", ".join(job["also_applied"])]
        for job in dispatch.own_jobs(db, profile_id, since, until)
    ]


def others_table(db: Session, profile_id: int, since: date | None,
                 until: date | None) -> tuple[list[str], list[list]]:
    """Everything handed to this profile, all three statuses on one list.

    One list rather than three, because the question a spreadsheet gets asked is
    "what happened to everything handed to me".
    """
    rows: list[list] = []
    for status in ("pending", "applied", "skipped"):
        for job in dispatch.others_jobs(db, profile_id, status, since, until):
            rows.append([job["company"], job["title"], job["url"], job["platform"],
                         job["found_by"], STANDING[status],
                         ", ".join(job["applied_by"]), job["skip_reason"]])
    return OTHERS_COLUMNS, rows


def standing_table(db: Session, profile_id: int, since: date | None,
                   until: date | None) -> tuple[list[str], list[list]]:
    """The pool, with this profile's standing against every row."""
    return ALL_COLUMNS, [
        [job["company"], job["title"], job["url"], job["platform"], job["found_by"],
         job["applications"], ", ".join(job["applied_by"]),
         STANDING[job["standing"]], (job["first_seen"] or "")[:10]]
        for job in dispatch.all_jobs(db, profile_id, since, until)
    ]


def profile_workbook(db: Session, profile: Profile, since: date | None,
                     until: date | None) -> tuple[bytes, str]:
    """This profile's three lists and its five counts. Returns (bytes, filename)."""
    book = Workbook()
    book.remove(book.active)  # the default sheet, before Summary takes first place

    _summary(book, f"MBS — {profile.name}",
             profile_summary(db, profile, since, until))
    _sheet(book, "Own jobs", *own_table(db, profile.id, since, until))
    _sheet(book, "Others' jobs", *others_table(db, profile.id, since, until))
    _sheet(book, "All jobs", *standing_table(db, profile.id, since, until))

    stamp = _window_line(since, until).replace(" ", "-")
    return _bytes(book), safe_filename(f"MBS {profile.name} {stamp}.xlsx")


# --------------------------------------------------------------------------- #
# The whole workspace — what a manager exports
# --------------------------------------------------------------------------- #

SEAT_COLUMNS = ["BD", "Profiles", "Own jobs", "Others' given", "Others' applied",
                "Skipped", "Pending", "Applied in all", "Dealt with %",
                "Share of applied %"]
PROFILE_COLUMNS = ["Profile", "Headline", "Held by", "Active", "Own jobs",
                   "Others' given", "Others' applied", "Skipped", "Pending",
                   "Applied in all", "Dealt with %", "Share of applied %"]
DAY_COLUMNS_HEAD = ["Date"]


def percent(part: int, whole: int) -> object:
    """A whole-number percentage, or blank when there is nothing to divide.

    Blank rather than zero: a chart skips an empty cell and draws a nought,
    and "nought per cent of nothing" is a sentence that misleads a manager
    reading down a column.
    """
    return round(100 * part / whole) if whole else ""


def _dealt(counts: dict) -> object:
    """Of the others' jobs handed over, how much has been acted on.

    Applied for or turned down both count: the question this answers is whether
    somebody is working their list, not which way they went on any one row.
    """
    given = counts.get("given", 0)
    return percent(given - counts.get("pending", 0), given)
POOL_COLUMNS = ["Company name", "Job title", "Job link", "Job platform",
                "Found by", "Applications", "Applied by", "First seen"]
PEOPLE_COLUMNS = ["Name", "Email", "Role", "Active", "Profiles"]


# The three tables below are pulled out of the workbook rather than written
# inside it, because the Google Sheet mirror sends the same rows somewhere else
# (see sheets.py). A row means one thing or the two disagree, and a manager
# reading the sheet and the manager reading the file would be looking at two
# different workspaces.

def workspace_summary(board: dict, since: date | None,
                      until: date | None) -> list[tuple[str, object]]:
    """The manager's counts, label and value, in the order they are read."""
    totals = board["totals"]
    return [
        ("Date range", _window_line(since, until)),
        (None, None),
        ("Applied in all", totals["applied"]),
        ("Own jobs found", totals["own"]),
        ("Others' jobs applied for", totals["from_others"]),
        ("Skipped", totals["skipped"]),
        ("Still pending", totals["pending"]),
        ("Others' jobs given out", totals["given"]),
        ("Jobs in the pool", totals["jobs"]),
        (None, None),
        ("BDs", totals["bds"]),
        ("Profiles", totals["profiles"]),
        ("Profiles nobody holds", totals["unassigned"]),
    ]


def bd_table(board: dict) -> tuple[list[str], list[list]]:
    """The five counts per BD, their profiles added together.

    Plus the two a manager acts on rather than reads: how much of what was
    handed to somebody they have got through, and how much of the team's output
    is theirs. Both are percentages, because the counts alone say more about how
    long somebody has been here than about how they are doing.
    """
    everyone = board["totals"].get("applied", 0)
    return SEAT_COLUMNS, [
        [seat["name"], ", ".join(seat["profiles"]), seat["own"], seat["given"],
         seat["from_others"], seat["skipped"], seat["pending"], seat["applied"],
         _dealt(seat), percent(seat["applied"], everyone)]
        for seat in board["people"]
    ]


def profile_table(board: dict) -> tuple[list[str], list[list]]:
    """The five counts per profile, with who holds it."""
    everyone = board["totals"].get("applied", 0)
    return PROFILE_COLUMNS, [
        [p["name"], p["headline"], p["bd"] or "nobody",
         "yes" if p["is_active"] else "no",
         p["counts"].get("own", 0), p["counts"].get("given", 0),
         p["counts"].get("from_others", 0), p["counts"].get("skipped", 0),
         p["counts"].get("pending", 0), p["counts"].get("applied", 0),
         _dealt(p["counts"]), percent(p["counts"].get("applied", 0), everyone)]
        for p in board["profiles"]
    ]


# A day's worth of gaps is worth filling so a chart does not join Friday to
# Monday and call it a flat line. A century of them is somebody having typed a
# date wrong, and is not worth ten thousand rows.
MAX_FILLED_DAYS = 400


def by_day_table(db: Session, since: date | None,
                 until: date | None) -> tuple[list[str], list[list]]:
    """Applications per day, a column per BD, oldest first.

    The shape a chart wants: dates down the side, people across the top, one
    number in each cell. It is the only table here that is about *when* rather
    than *how many*, and it is the one that shows a week somebody was off or a
    Monday the whole team lost to a platform being down.

    The day a row counts against is the one `dispatch` works out — what somebody
    typed into the date column, or when the row was filed if that cannot be
    read — so this and every count beside it agree about what "Tuesday" means.
    """
    rows = db.execute(
        select(Application.applied_on, Application.created_at, User.name)
        .join(Profile, Profile.id == Application.profile_id)
        .outerjoin(User, User.id == Profile.user_id)).all()

    per_day: dict[date, dict[str, int]] = {}
    people: set[str] = set()
    for applied_on, created_at, holder in rows:
        day = dispatch.as_date(applied_on, created_at)
        if not dispatch.within(day, since, until) or day is None:
            continue
        who = holder or "nobody"
        people.add(who)
        per_day.setdefault(day, {})[who] = per_day.setdefault(day, {}).get(who, 0) + 1

    if not per_day:
        return DAY_COLUMNS_HEAD + ["Everyone"], []

    days = sorted(per_day)
    first, last = days[0], days[-1]
    if (last - first).days <= MAX_FILLED_DAYS:
        days = [first + timedelta(days=n) for n in range((last - first).days + 1)]

    names = sorted(people)
    columns = DAY_COLUMNS_HEAD + names + ["Everyone"]
    out: list[list] = []
    for day in days:
        counts = per_day.get(day, {})
        out.append([day.isoformat()] + [counts.get(who, 0) for who in names]
                   + [sum(counts.values())])
    return columns, out


def pool_table(db: Session, since: date | None,
               until: date | None) -> tuple[list[str], list[list]]:
    """The whole pool through one window, nobody's standing on it."""
    return POOL_COLUMNS, [
        [job["company"], job["title"], job["url"], job["platform"], job["found_by"],
         job["applications"], ", ".join(job["applied_by"]),
         (job["first_seen"] or "")[:10]]
        for job in dispatch.all_jobs(db, None, since, until)
    ]


def workspace_workbook(db: Session, board: dict, people: list[dict],
                       since: date | None, until: date | None) -> tuple[bytes, str]:
    """Every number on the manager's screens, plus the pool behind them."""
    book = Workbook()
    book.remove(book.active)

    _summary(book, "MBS — the whole workspace",
             workspace_summary(board, since, until))

    _sheet(book, "By BD", *bd_table(board), url_column=None)

    _sheet(book, "By profile", *profile_table(board), url_column=None)
    _sheet(book, "By day", *by_day_table(db, since, until), url_column=None)
    _sheet(book, "All jobs", *pool_table(db, since, until))

    _sheet(book, "People", PEOPLE_COLUMNS, [
        [person["name"], person["email"], person["role"],
         "yes" if person["is_active"] else "no", ", ".join(person["profiles"])]
        for person in people
    ], url_column=None)

    stamp = _window_line(since, until).replace(" ", "-")
    return _bytes(book), safe_filename(f"MBS workspace {stamp}.xlsx")


# --------------------------------------------------------------------------- #
# The two workbooks the sheet importer needs
# --------------------------------------------------------------------------- #

# The entry grid's six columns, in the order it asks for them. A sheet with
# these headings imports with nothing to think about, which is the whole reason
# the template exists — "the same attributes as the system" should be something
# somebody can download rather than something they have to be told.
# The Google Sheet mirror's order, so a BD lining an old sheet up against the
# team's file and one filling in this template are doing the same thing.
TEMPLATE_COLUMNS = ["Applied on", "Company name", "Job title", "Job link",
                    "Job platform", "Email"]

LEFTOVER_COLUMNS = ["Sheet", "Line", "Why it did not go in", "Company name",
                    "Job title", "Job link", "Job platform", "Email", "Date"]


def template_workbook(platforms: list[str]) -> tuple[bytes, str]:
    """The six headings and nothing under them, plus a page explaining them.

    Deliberately no example row. A template that ships with a line of plausible
    data in it is a template somebody fills in around, uploads, and files a
    fictional job out of. The worked example is on the second sheet, where it
    can be read and cannot be imported.
    """
    board = platforms[0] if platforms else "LinkedIn"

    book = Workbook()
    book.remove(book.active)
    _sheet(book, "Jobs", TEMPLATE_COLUMNS, [])

    # Written as sentences rather than as a little table on purpose: a page of
    # label-and-value pairs headed "Job link" is a page the importer would read
    # back as a sheet of its own.
    notes = book.create_sheet("How this is read")
    for line in [
        ("The six columns", "Applied on · Company name · Job title "
                            "· Job link · Job platform · Email"),
        ("A line looks like", "2026-07-14 · Northwind Labs · Senior RAG Engineer · "
                              "https://www.linkedin.com/jobs/view/3912345678 "
                              f"· {board} · you@yourdomain.com"),
        ("", ""),
        ("Dates", "2026-07-14, 14/07/2026, 07/14/2026 and 14 Jul 2026 are all "
                  "read, and so is a real Excel date. 03/04/2026 is read the "
                  "way the rest of the same file reads — if any line has a "
                  "day over 12 first, the whole file is day-first."),
        ("", ""),
        ("What goes in", ""),
        ("", "Every line is a job this profile found and applied for. It is filed "
             "as an own job, and handed to every other live profile as an "
             "others' job — exactly as if it had been typed into the grid."),
        ("", ""),
        ("Only the headings matter", ""),
        ("", "The columns can be in any order, and the header row does not have "
             "to be the first row. Common spellings are understood: Client, "
             "Role, Link, Portal, Applied on, and so on."),
        ("", ""),
        ("A line needs identifying", ""),
        ("", "A job link, or a company and a job title. A line with only a date "
             "and an email cannot be filed, and comes back in the leftovers "
             "file so it can be fixed."),
        ("", ""),
        ("Uploading twice is safe", ""),
        ("", "A posting already on this profile's record is counted and left "
             "alone. If part of a large sheet did not go in, upload the same "
             "file again — only what is missing is added."),
        ("", ""),
        ("Everything is marked applied", ""),
        ("", "Every line is filed as applied for, whatever any Status column "
             "says. Only put in the sheet what this profile really applied for."),
        ("", ""),
        ("The Google Sheet's own columns", ""),
        ("", "A tab from the team's Google Sheet uploads as it is: Applied on, "
             "Company name, Job title, Job link, Job platform and Email are "
             "read, and BD, Own or others, Found by and Filed at are ignored "
             "(Filed at stands in for a blank Applied on). A whole downloaded "
             "workbook reads only the tab named after this profile."),
    ]:
        notes.append(list(line))
    notes.column_dimensions["A"].width = 30
    notes.column_dimensions["B"].width = 96
    for cell in notes["A"]:
        if cell.value:
            cell.font = Font(bold=True)
    for cell in notes["B"]:
        cell.alignment = Alignment(wrap_text=True, vertical="top")

    return _bytes(book), "MBS import template.xlsx"


def leftovers_workbook(profile_name: str, batch: dict,
                       rows: list) -> tuple[bytes, str]:
    """The lines an upload could not file, in the shape that imports back in.

    Deliberately the template's own columns plus three that say where the line
    came from and what was wrong with it. Fix the row, delete the first three
    columns or leave them — they are ignored on the way back in — and upload.
    """
    book = Workbook()
    book.remove(book.active)

    _summary(book, f"MBS — lines left over from {batch.get('filename') or 'an upload'}", [
        ("Profile", profile_name),
        ("Uploaded", (batch.get("at") or "")[:19].replace("T", " ")),
        ("Rows in the file", batch.get("rows", 0)),
        (None, None),
        ("New postings added", batch.get("added", 0)),
        ("Already in the pool", batch.get("known", 0)),
        ("Already on this profile", batch.get("duplicate", 0)),
        ("Repeated within the file", batch.get("repeated", 0)),
        ("Marked not applied for", batch.get("not_applied", 0)),
        ("Could not be read", batch.get("unusable", 0)),
        (None, None),
        ("Left over, below", len(rows)),
    ])

    _sheet(book, "Left over", LEFTOVER_COLUMNS, [
        [row.sheet, row.line, row.reason, row.company, row.title, row.url,
         row.platform, row.email, row.applied_on]
        for row in rows
    ])

    stamp = safe_filename(batch.get("filename") or "upload").rsplit(".", 1)[0]
    return _bytes(book), safe_filename(f"MBS left over from {stamp}.xlsx")
