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
import re
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import dispatch
from .matching import fingerprint
from .models import Import, ImportRow, Profile, User

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
    "status": ("status", "state", "stage", "outcome", "result", "response"),
}

# A row needs one of these to be a posting at all. A line carrying only an
# email and a date is a line somebody left behind, not a job.
IDENTIFYING = ("company", "title", "url")

# Read off a Status column, and read narrowly on purpose. A sheet whose status
# column says "Rejected", "No reply" or "Interview" is describing what happened
# *after* applying, and withholding those rows would be the very thing this
# feature exists to prevent. Only a status that plainly says the BD never
# applied stops a row — which is also what keeps a workbook exported from MBS
# and uploaded straight back from inventing an application per pending row.
#
# Nothing ambiguous belongs here. "No", "None" and "N/A" were all considered
# and left out: each is as likely to mean "no reply" as "not applied", and the
# cost of reading one wrong is a row withheld, which is the one failure this
# whole feature exists to prevent. A blank is not a statement either, and most
# cells in a hand-kept status column are blank.
NOT_APPLIED = frozenset({
    "skipped", "skip", "pending", "not applied", "didnt apply", "did not apply",
    "not yet", "to apply", "to be applied", "yet to apply", "will apply",
})


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


def _csv_grid(data: bytes) -> list[tuple[str, list[list[str]]]]:
    text = _decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [[_text(cell) for cell in row]
            for row in csv.reader(io.StringIO(text), dialect)]
    return [("Sheet", rows)]


def _xlsx_grid(data: bytes) -> list[tuple[str, list[list[str]]]]:
    """Every sheet in the workbook, as text.

    Read in full rather than in openpyxl's read-only mode, because a read-only
    cell carries no hyperlink. Plenty of old sheets have the word "Apply" in
    the link column with the address hidden behind it, and the address is the
    only part of that row worth having. MAX_BYTES is what keeps holding a whole
    workbook in memory a reasonable thing to do.
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

    grids: list[tuple[str, list[list[str]]]] = []
    for page in book.worksheets:
        rows: list[list[str]] = []
        for line in page.iter_rows():
            cells = []
            for cell in line:
                shown = _text(cell.value)
                target = getattr(cell.hyperlink, "target", None)
                # The visible text wins unless it is not a link and the cell is
                # hiding one — "Apply" over https://… is the case this is for.
                if target and not re.match(r"^\s*https?://", shown, re.I):
                    shown = str(target).strip()
                cells.append(shown)
            rows.append(cells)
        grids.append((page.title, rows))
    book.close()
    return grids


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


def read_rows(data: bytes, filename: str) -> tuple[list[dict], list[str]]:
    """Every data row in the file, and the names of the sheets they came from.

    Each row is {sheet, line, company, title, url, platform, email,
    applied_on, status}. `line` is the row number Excel shows, so a report
    saying "line 812" can be found by scrolling to 812.
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

    out: list[dict] = []
    read: list[str] = []
    for name, rows in grids:
        found = _header(rows)
        if not found:
            continue  # a Summary sheet, a notes tab, a blank one
        start, mapping = found
        before = len(out)
        for line_no, row in enumerate(rows[start + 1:], start=start + 2):
            values = {key: (_text(row[column]) if column < len(row) else "")
                      for column, key in mapping.items()}
            if not any(values.values()):
                continue  # a spacer row, or the blank tail of a used range
            out.append({"sheet": name, "line": line_no,
                        "company": values.get("company", ""),
                        "title": values.get("title", ""),
                        "url": values.get("url", ""),
                        "platform": values.get("platform", ""),
                        "email": values.get("email", ""),
                        "applied_on": values.get("applied_on", ""),
                        "status": values.get("status", "")})
        if len(out) > before:
            read.append(name)

    if not read:
        raise SheetError(
            "No column headings were recognised. The sheet needs a header row "
            "with at least a job link, or a company and a job title — "
            "download the template to see the six columns.")
    return out, read


# --------------------------------------------------------------------------- #
# Filing them
# --------------------------------------------------------------------------- #

# The six buckets every row lands in, and they are exhaustive: added + known +
# duplicate + repeated + not_applied + unusable is the number of rows read.
# That equality is the feature. A BD who is told 2,750 of 3,000 went in can
# read the other 250 off the same report rather than wondering.
COUNTS = ("added", "known", "duplicate", "repeated", "not_applied", "unusable")

WHY = {
    "unusable": "Nothing in the row identified a posting — no link, "
                "no company and no job title.",
    "not_applied": "The sheet's status column says it was not applied for.",
}


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
        data: bytes) -> Import:
    """File a whole sheet against `profile`. Commits as it goes.

    Raises SheetError, before anything is written, if the file cannot be read
    at all. After that it does not raise: a row that cannot be filed is counted
    and kept, because thirty bad lines are not a reason to reject two thousand
    nine hundred and seventy good ones.
    """
    rows, sheets = read_rows(data, filename)

    batch = Import(profile_id=profile.id, user_id=user.id if user else None,
                   filename=filename[:255], digest=digest_of(data),
                   sheets=", ".join(sheets)[:400], rows=len(rows))
    db.add(batch)
    db.commit()

    live = dispatch.live_profiles(db)
    seen: set[str] = set()
    tally = {key: 0 for key in COUNTS}

    def keep(row: dict, reason: str) -> None:
        db.add(ImportRow(import_id=batch.id, sheet=row["sheet"][:64],
                         line=row["line"], reason=WHY[reason][:120],
                         company=row["company"][:200], title=row["title"][:300],
                         url=row["url"], platform=row["platform"][:120],
                         email=row["email"][:255], applied_on=row["applied_on"][:40]))

    for index, row in enumerate(rows, start=1):
        if _slug(row["status"]) in NOT_APPLIED:
            tally["not_applied"] += 1
            keep(row, "not_applied")
        else:
            mark, _tier = fingerprint(row["url"], row["title"], row["company"])
            if not mark:
                tally["unusable"] += 1
                keep(row, "unusable")
            elif mark in seen:
                # The same posting twice in one sheet. Counted apart from
                # `duplicate` because the two mean different things to whoever
                # reads the report: one is their sheet repeating itself, the
                # other is the system already holding the row.
                tally["repeated"] += 1
            else:
                seen.add(mark)
                tally[dispatch.log_find(
                    db, profile, row, live, import_id=batch.id)["status"]] += 1

        if index % CHUNK == 0:
            for key in COUNTS:
                setattr(batch, key, tally[key])
            db.commit()

    for key in COUNTS:
        setattr(batch, key, tally[key])
    batch.finished = True
    db.commit()
    return batch


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
        "left_over": batch.not_applied + batch.unusable,
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
