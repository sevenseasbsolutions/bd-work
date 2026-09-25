"""Reading somebody's old sheet back into the pool.

A team that has been working out of a spreadsheet for three months does not
start using MBS on the understanding that the three months are gone. So the
sheet comes in: every line is a job that profile found and applied for, which
means every line also lands on every other live profile's list as an others'
job — the same thing that happens when a BD types one in by hand. There is one
way into the pool, and this is a second door onto it, not a second pool.

Three things make an upload safe to repeat, which is the property that actually
matters at three thousand lines:

  it dedupes on the fingerprint   a posting already on this profile's record is
                                  counted and skipped, never filed twice
  it commits as it goes           a run that dies at line 1,400 keeps 1,400
  every line is accounted for     the six counts add up to the number of rows
                                  read, exactly, and the ones that did not go
                                  in are kept so they can be downloaded, fixed
                                  and sent again

Which together mean the answer to "250 of my 3,000 never arrived" is: upload
the same file again. The 2,750 already on record cost a lookup each and change
nothing; the 250 go in.
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import dispatch
from .matching import fingerprint, is_posting, normalize_text
from .models import Import, ImportRow, Profile, User

log = logging.getLogger("mbs.imports")

# Anything bigger than this is not a BD's job sheet, and reading it would be a
# way to take the server's memory out from the other side of a login form.
MAX_BYTES = 15 * 1024 * 1024

# How many rows go in between commits. Small enough that a run cut off halfway
# loses almost nothing, large enough that the commits are not the slow part.
CHUNK = 200

# How far down a sheet to look for the header. Hand-made sheets carry a title,
# a date, a blank line and *then* the columns.
HEADER_SCAN = 12


# --------------------------------------------------------------------------- #
# What a column is called
# --------------------------------------------------------------------------- #

# The six the system itself writes are first in each list — a sheet exported
# from MBS reads back in without a thought. The rest are what people actually
# type at the top of a column, collected rather than invented.
ALIASES: dict[str, tuple[str, ...]] = {
    "company": ("company name", "company", "client", "client name", "customer",
                "employer", "organisation", "organization", "firm", "business"),
    "title": ("job title", "title", "role", "position", "job role", "job name",
              "designation", "post", "vacancy"),
    "url": ("job link", "link", "url", "job url", "job post", "posting",
            "job posting", "job link url", "apply link", "application link",
            "jobs link", "web link", "job address"),
    "platform": ("job platform", "platform", "source", "portal", "job board",
                 "board", "site", "website", "channel", "found on"),
    "email": ("email", "email address", "email id", "mail", "applied from",
              "from email", "account", "applied with", "bidder email"),
    "applied_on": ("date", "applied on", "applied date", "date applied",
                   "apply date", "application date", "applied at", "day"),
    # Only read when the applied-on cell is blank. It is the Google Sheet
    # mirror's own last column, so a tab downloaded from there keeps its days
    # even on a line whose "Applied on" somebody cleared.
    "filed_at": ("filed at", "filed on", "logged at", "logged on",
                 "created at", "timestamp"),
}

# A row needs one of these to be a posting at all. A line carrying only an
# email and a date is a line somebody left behind, not a job.
IDENTIFYING = ("company", "title", "url")

# There is deliberately no Status column. Everything in an uploaded sheet is a
# job this profile applied for — that is what the upload means — so a status
# cell is never a reason to hold a line back. A line withheld is the one
# failure this feature exists to prevent.


def _slug(value: object) -> str:
    """A header as a comparable key: lowercase words, nothing else."""
    return re.sub(r"\s+", " ",
                  re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())).strip()


_KEY_BY_HEADER = {_slug(name): key
                  for key, names in ALIASES.items() for name in names}


def _text(value: object) -> str:
    """A cell as the string the rest of MBS works in.

    Excel hands back real datetimes for a date column and floats for anything
    numeric. `2026-09-14 00:00:00` and `1234.0` are both things nobody typed,
    and neither reads as what was meant.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


# --------------------------------------------------------------------------- #
# Turning a file into rows
# --------------------------------------------------------------------------- #

class SheetError(ValueError):
    """Something about the file itself, said in words a BD can act on."""


def _decode(data: bytes) -> str:
    """A CSV's text, whatever a spreadsheet saved it as.

    utf-8-sig first, because Excel writes the byte-order mark and `csv` would
    otherwise hand the first heading back with an invisible character glued to
    it. cp1252 last because it cannot fail, which is what makes it the floor.
    """
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("cp1252", "replace")


# A sheet as text: (tab name, rows of cells, {(row, column): hidden link}).
Grid = tuple[str, list[list[str]], dict[tuple[int, int], str]]


def _csv_grid(data: bytes) -> list[Grid]:
    text = _decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [[_text(cell) for cell in row]
            for row in csv.reader(io.StringIO(text), dialect)]
    return [("Sheet", rows, {})]


def _xlsx_grid(data: bytes) -> list[Grid]:
    """Every sheet in the workbook, as text, with the links hidden in cells.

    Read in full rather than in openpyxl's read-only mode, because a read-only
    cell carries no hyperlink. Plenty of old sheets have the word "Apply" in
    the link column with the address hidden behind it, or the job title itself
    linked to the posting — and the address is the only part of that row worth
    having. MAX_BYTES is what keeps holding a whole workbook in memory a
    reasonable thing to do.

    The links are kept apart from the text rather than swapped in for it. A
    company name linked to the company's LinkedIn page is still a company
    name; which hidden link, if any, is the job link is `read_rows`' call.
    """
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        book = load_workbook(io.BytesIO(data), data_only=True)
    except InvalidFileException:
        raise SheetError(
            "That looks like an older .xls file. Open it and use "
            "File › Save As › Excel Workbook (.xlsx), then try again.")
    except Exception:
        raise SheetError("That file could not be opened as a spreadsheet.")

    grids: list[Grid] = []
    for page in book.worksheets:
        rows: list[list[str]] = []
        links: dict[tuple[int, int], str] = {}
        for index, line in enumerate(page.iter_rows()):
            rows.append([_text(cell.value) for cell in line])
            for column, cell in enumerate(line):
                target = str(getattr(cell.hyperlink, "target", None) or "").strip()
                if _is_link(target):
                    links[(index, column)] = target
        grids.append((page.title, rows, links))
    book.close()
    return grids


def _is_link(text: str) -> bool:
    return bool(re.match(r"^\s*https?://", text or "", re.I))


def _job_link(typed: str, hidden: dict[str, str]) -> str:
    """The posting's address, from wherever the sheet keeps it.

    Old sheets keep it in three places: typed into the link column, hidden
    behind the link column ("Apply" over https://…), or hidden behind the job
    title — with the link column holding the company's website instead. The
    first of these that names a posting wins. A company homepage is kept only
    when nothing better exists, and it never identifies a job on its own
    (see `matching.is_posting`).
    """
    shown = typed if _is_link(typed) else ""
    candidates = [shown, hidden.get("url", ""), hidden.get("title", "")]
    # A platform's own job id beats any other address: a Glassdoor company
    # page in the link column is a long path too, but only the LinkedIn link
    # behind the title names one opening.
    for link in candidates:
        if link and fingerprint(link, "", "")[1] == "L1":
            return link
    for link in candidates:
        if link and is_posting(link):
            return link
    return next((link for link in candidates if link), typed)


def _header(rows: list[list[str]]) -> tuple[int, dict[int, str]] | None:
    """(row index, {column index: key}) for the best header row, or None.

    "Best" is the row that recognises the most columns. A sheet needs one of
    company, title or link, and then either a second recognised column or a
    link column with links under it — a single column of addresses is a
    perfectly good sheet, and refusing it would be pedantry.

    The "with links under it" is what stops a page of prose being read as a
    sheet. One line reading `Job link | https://…` is a sentence about a column,
    not a column; the difference is whether the rows below it carry addresses.
    """
    best: tuple[int, dict[int, str]] | None = None
    for index, row in enumerate(rows[:HEADER_SCAN]):
        mapping: dict[int, str] = {}
        for column, cell in enumerate(row):
            key = _KEY_BY_HEADER.get(_slug(cell))
            # The first column to claim a key keeps it: a sheet with "Date"
            # twice means the first one, not whichever happens to come last.
            if key and key not in mapping.values():
                mapping[column] = key
        keys = set(mapping.values())
        if not keys & set(IDENTIFYING):
            continue
        if len(keys) < 2:
            if "url" not in keys:
                continue
            at = next(column for column, key in mapping.items() if key == "url")
            if not any(re.match(r"^\s*https?://", line[at], re.I)
                       for line in rows[index + 1:index + 6] if at < len(line)):
                continue
        if best is None or len(keys) > len(set(best[1].values())):
            best = (index, mapping)
    return best


def _same_tab(title: str, wanted: str) -> bool:
    """Whether a workbook tab is the one named after this profile.

    Compared on the first 31 characters, because that is all an .xlsx allows
    and a Google Sheet downloaded as one is cut down to it.
    """
    return _slug(title[:31]) == _slug(wanted[:31]) != ""


def read_rows(data: bytes, filename: str,
              tab: str = "") -> tuple[list[dict], list[str]]:
    """Every data row in the file, and the names of the sheets they came from.

    Each row is {sheet, line, company, title, url, platform, email,
    applied_on}. `line` is the row number Excel shows, so a report saying
    "line 812" can be found by scrolling to 812.

    `tab` is the profile's tab name. The team's Google Sheet has a tab per
    profile, and a BD who downloads the whole file and uploads it must get
    their own tab — not every colleague's work filed as theirs. So when one of
    several readable tabs carries that name, it is the only one read. A
    workbook without such a tab (July, August, September…) is read whole.
    """
    if not data:
        raise SheetError("That file is empty.")
    if len(data) > MAX_BYTES:
        raise SheetError(f"That file is larger than {MAX_BYTES // (1024 * 1024)} MB.")

    lowered = filename.lower()
    if lowered.endswith((".csv", ".tsv", ".txt")):
        grids = _csv_grid(data)
    elif lowered.endswith((".xlsx", ".xlsm")):
        grids = _xlsx_grid(data)
    elif lowered.endswith(".xls"):
        raise SheetError(
            "That is an older .xls file. Open it and use File › Save As "
            "› Excel Workbook (.xlsx), then try again.")
    else:
        raise SheetError("Upload an .xlsx or a .csv.")

    pages: list[tuple[str, list[dict]]] = []
    for name, rows, links in grids:
        found = _header(rows)
        if not found:
            continue  # a Summary sheet, a notes tab, a blank one
        start, mapping = found
        column_of = {key: column for column, key in mapping.items()}
        lines: list[dict] = []
        for index in range(start + 1, len(rows)):
            row = rows[index]
            values = {key: (_text(row[column]) if column < len(row) else "")
                      for column, key in mapping.items()}
            if not any(values.values()):
                continue  # a spacer row, or the blank tail of a used range
            hidden = {key: links.get((index, column_of[key]), "")
                      for key in ("url", "title") if key in column_of}
            lines.append({"sheet": name, "line": index + 1,
                          "company": values.get("company", ""),
                          "title": values.get("title", ""),
                          "url": _job_link(values.get("url", ""), hidden),
                          "platform": values.get("platform", ""),
                          "email": values.get("email", ""),
                          "applied_on": values.get("applied_on", "")
                                        or values.get("filed_at", "")})
        if lines:
            pages.append((name, lines))

    if not pages:
        raise SheetError(
            "No column headings were recognised. The sheet needs a header row "
            "with at least a job link, or a company and a job title — "
            "download the template to see the six columns.")

    if len(pages) > 1 and tab:
        own = [page for page in pages if _same_tab(page[0], tab)]
        if own:
            pages = own

    _settle_dates([line for _, lines in pages for line in lines])
    return ([line for _, lines in pages for line in lines],
            [name for name, _ in pages])


# --------------------------------------------------------------------------- #
# Which day each line was applied on
# --------------------------------------------------------------------------- #

# 3/4/2026 is the 3rd of April to one BD and the 4th of March to the next, and
# a sheet that is read the wrong way round files a quarter's work in the wrong
# months. One sheet is kept by one person, so it is settled per file: any line
# whose first number cannot be a month (14/07) makes the file day-first, any
# whose second cannot (07/14) makes it month-first, and a file that says
# neither is read day-first, the way the rest of MBS reads a typed date.
_NUMERIC = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?:[ T,].*)?$")
_ISO = re.compile(r"^(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})(?:[ T,].*)?$")

# An Excel date that lost its formatting on the way to a CSV is a bare day
# count. This range is 1954 to 2119, which no other number in a date column is.
_SERIAL = re.compile(r"^(\d{5})(?:\.\d+)?$")


def _day(text: str, month_first: bool) -> date | None:
    text = text.strip()
    if not text:
        return None
    try:
        hit = _ISO.match(text)
        if hit:
            return date(int(hit[1]), int(hit[2]), int(hit[3]))
        hit = _NUMERIC.match(text)
        if hit:
            first, second, year = int(hit[1]), int(hit[2]), int(hit[3])
            year += 2000 if year < 100 else 0
            month, day_ = (first, second) if month_first else (second, first)
            return date(year, month, day_)
        hit = _SERIAL.match(text)
        if hit and 20000 <= int(hit[1]) <= 80000:
            return date(1899, 12, 30) + timedelta(days=int(hit[1]))
    except ValueError:
        return None
    return dispatch.as_date(text, None)


def _settle_dates(lines: list[dict]) -> None:
    """Rewrite every readable date as YYYY-MM-DD, in place.

    Stored settled rather than as typed, so the date window, the manager's
    counts and the Google Sheet all read the same day off it for ever after. A
    date that cannot be read is left exactly as it was typed — the line still
    goes in, it just counts against the day it was uploaded — and `dated` on
    the line says which happened, so the report can say how many.
    """
    day_first = month_first = False
    for line in lines:
        hit = _NUMERIC.match(line["applied_on"].strip())
        if hit:
            day_first |= int(hit[1]) > 12
            month_first |= int(hit[2]) > 12
    order = month_first and not day_first

    for line in lines:
        settled = _day(line["applied_on"], order)
        line["dated"] = settled is not None
        if settled:
            line["applied_on"] = settled.isoformat()


# --------------------------------------------------------------------------- #
# Filing them
# --------------------------------------------------------------------------- #

# The six buckets every row lands in, and they are exhaustive: added + known +
# duplicate + repeated + not_applied + unusable is the number of rows read.
# That equality is the feature. A BD who is told 2,750 of 3,000 went in can
# read the other 250 off the same report rather than wondering.
#
# `not_applied` is only ever non-zero on an upload made before a Status column
# stopped holding lines back. It stays so those uploads still add up.
COUNTS = ("added", "known", "duplicate", "repeated", "clashing",
          "not_applied", "unusable")

WHY = {
    "unusable": "Nothing in the row identified a posting — no link, "
                "no company and no job title.",
    "clashing": "Same job link as an earlier line, but a different company "
                "— one of the two links is probably on the wrong line.",
    "refused": "The database would not take this line — check it for a "
               "pasted-in page of text.",
}


def _clash(first: str, then: str) -> bool:
    """Whether two company names on one link are plainly two companies.

    Loose on purpose: "Kettering Health" and "Kettering Health Network", or
    "Tennova Healthcare- North Knox" and "Tennova Healthcare", are one company
    typed twice. Only names sharing no word at all count as a clash.
    """
    a, b = set(normalize_text(first).split()), set(normalize_text(then).split())
    return bool(a and b and not a & b)


def digest_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def earlier_upload(db: Session, profile_id: int, digest: str) -> Import | None:
    """The last time this exact file went in on this profile, if it ever did.

    So the screen can say "you uploaded this same sheet on Tuesday" rather than
    leaving somebody to wonder whether they are about to double everything.
    """
    return db.scalars(
        select(Import).where(Import.profile_id == profile_id,
                             Import.digest == digest)
        .order_by(Import.created_at.desc())
    ).first()


def run(db: Session, profile: Profile, user: User | None, filename: str,
        data: bytes) -> tuple[Import, int]:
    """File a whole sheet against `profile`. Commits as it goes.

    Returns the upload and how many of its filed lines had no readable date.

    Raises SheetError, before anything is written, if the file cannot be read
    at all. After that it does not raise: a row that cannot be filed is counted
    and kept, because thirty bad lines are not a reason to reject two thousand
    nine hundred and seventy good ones.
    """
    from .sheets import tab_name
    rows, sheets = read_rows(data, filename, tab_name(profile.name))

    batch = Import(profile_id=profile.id, user_id=user.id if user else None,
                   filename=filename[:255], digest=digest_of(data),
                   sheets=", ".join(sheets)[:400], rows=len(rows))
    db.add(batch)
    db.commit()

    live = dispatch.live_profiles(db)
    # fingerprint -> the company on the first line that had it
    seen: dict[str, str] = {}
    tally = {key: 0 for key in COUNTS}
    # Lines filed with no readable date. They are in, and applied, but they
    # count against the day of the upload — worth saying, not worth refusing.
    undated = 0

    def keep(row: dict, reason: str) -> None:
        db.add(ImportRow(import_id=batch.id, sheet=row["sheet"][:64],
                         line=row["line"], reason=WHY[reason][:120],
                         company=row["company"][:200], title=row["title"][:300],
                         url=row["url"], platform=row["platform"][:120],
                         email=row["email"][:255], applied_on=row["applied_on"][:40]))

    for index, row in enumerate(rows, start=1):
        mark, _tier = fingerprint(row["url"], row["title"], row["company"])
        if not mark:
            tally["unusable"] += 1
            keep(row, "unusable")
        elif mark in seen and _clash(seen[mark], row["company"]):
            # One link, two companies. Filing it as a repeat would lose one
            # job without a word; filing it as its own job under somebody
            # else's link would be worse. It goes back to be looked at.
            tally["clashing"] += 1
            keep(row, "clashing")
        elif mark in seen:
            # The same posting twice in one sheet. Counted apart from
            # `duplicate` because the two mean different things to whoever
            # reads the report: one is their sheet repeating itself, the
            # other is the system already holding the row.
            tally["repeated"] += 1
        else:
            seen[mark] = row["company"]
            # One line the database refuses must not take the rest of the
            # file down with it. It is rolled back on its own, counted, and
            # handed back in the leftovers file like any other.
            try:
                with db.begin_nested():
                    filed = dispatch.log_find(db, profile, row, live,
                                              import_id=batch.id)
            except Exception:
                log.exception("import %s: line %s refused", batch.id, row["line"])
                tally["unusable"] += 1
                keep(row, "refused")
                continue
            tally[filed["status"]] += 1
            if not row["dated"]:
                undated += 1

        if index % CHUNK == 0:
            for key in COUNTS:
                setattr(batch, key, tally[key])
            db.commit()

    for key in COUNTS:
        setattr(batch, key, tally[key])
    batch.finished = True
    db.commit()
    return batch, undated


# --------------------------------------------------------------------------- #
# Reading it back
# --------------------------------------------------------------------------- #

def batch_out(batch: Import, holder: str = "") -> dict:
    return {
        "id": batch.id, "filename": batch.filename, "sheets": batch.sheets,
        "by": holder, "digest": batch.digest, "finished": batch.finished,
        "at": batch.created_at.isoformat() if batch.created_at else None,
        "rows": batch.rows,
        # What is downloadable from this upload: the lines it could not file.
        "left_over": batch.not_applied + batch.unusable + batch.clashing,
        **{key: getattr(batch, key) for key in COUNTS},
    }


def history(db: Session, profile_id: int) -> list[dict]:
    """Every upload against this profile, newest first."""
    rows = db.execute(
        select(Import, User.name).outerjoin(User, User.id == Import.user_id)
        .where(Import.profile_id == profile_id)
        .order_by(Import.created_at.desc(), Import.id.desc())
    ).all()
    return [batch_out(batch, holder or "") for batch, holder in rows]


def leftovers(db: Session, import_id: int) -> list[ImportRow]:
    """The lines an upload could not file, in the order they were in the sheet."""
    return list(db.scalars(
        select(ImportRow).where(ImportRow.import_id == import_id)
        .order_by(ImportRow.id)
    ).all())
