"""Uploading somebody's old sheet, and uploading it again.

The promise this feature makes is narrow and testable: every line of the file
is accounted for, and sending the same file twice adds only what is missing.
Both are asserted below against real workbooks read by the real routes.
"""
from __future__ import annotations

import io

from openpyxl import Workbook, load_workbook

from helpers import log, make_bd, make_profile
from conftest import sign_in


# --------------------------------------------------------------------------- #
# Building a sheet to upload
# --------------------------------------------------------------------------- #

MBS_HEADERS = ["Company name", "Job title", "Job link", "Job platform",
               "Email", "Date"]


# The Google Sheet mirror's tab, column for column (sheets.APPLIED_COLUMNS).
GOOGLE_HEADERS = ["Applied on", "BD", "Company name", "Job title", "Job link",
                  "Job platform", "Email", "Own or others", "Found by",
                  "Filed at"]


def sheet(rows, headers=None, lead_in=(), name="Jobs"):
    """An .xlsx as bytes. `lead_in` is whatever sits above the header row."""
    book = Workbook()
    page = book.active
    page.title = name
    for line in lead_in:
        page.append(list(line))
    page.append(list(headers or MBS_HEADERS))
    for row in rows:
        page.append(list(row))
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def job_rows(count, start=1, company="Northwind", platform="LinkedIn"):
    """`count` distinct postings, each with a link of its own."""
    return [[f"{company} {n}", f"Engineer {n}",
             f"https://www.linkedin.com/jobs/view/39120000{n:02d}",
             platform, "bd@mbs.co", "2026-07-14"]
            for n in range(start, start + count)]


def upload(client, headers, profile_id, data, filename="old sheet.xlsx"):
    reply = client.post(
        f"/profiles/{profile_id}/import", headers=headers,
        files={"file": (filename, data,
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet")})
    assert reply.status_code == 200, reply.text
    return reply.json()


def workspace(client, manager, bds=("Ayesha", "Bilal")):
    """One profile each for a couple of BDs. Returns [(headers, profile), ...]."""
    out = []
    for index, name in enumerate(bds):
        person = make_bd(client, manager, name, f"{name.lower()}@mbs.co")
        profile = make_profile(client, manager, f"{name} — Engineer", person["id"])
        out.append((sign_in(client, f"{name.lower()}@mbs.co", "secret"), profile))
    return out


# --------------------------------------------------------------------------- #
# The straight case
# --------------------------------------------------------------------------- #

def test_a_sheet_lands_as_own_jobs_and_on_everybody_elses_list(client, manager):
    (mine, ayesha), (theirs, bilal) = workspace(client, manager)

    report = upload(client, mine, ayesha["id"], sheet(job_rows(12)))

    assert report["rows"] == 12
    assert report["added"] == 12
    assert report["unusable"] == 0
    assert report["finished"] is True

    own = client.get(f"/profiles/{ayesha['id']}/own", headers=mine).json()
    assert len(own) == 12
    assert own[0]["company"].startswith("Northwind")
    assert own[0]["applied_on"] == "2026-07-14"
    assert own[0]["email"] == "bd@mbs.co"
    assert own[0]["platform"] == "LinkedIn"

    # The whole point of the pool: what one profile found is everybody's work.
    pending = client.get(f"/profiles/{bilal['id']}/others",
                         headers=theirs, params={"status": "pending"}).json()
    assert len(pending) == 12
    assert pending[0]["found_by"] == "Ayesha"   # the BD holding the finder


def test_every_line_is_accounted_for(client, manager):
    """added + known + duplicate + repeated + not_applied + unusable == rows."""
    (mine, ayesha), _ = workspace(client, manager)
    rows = job_rows(6)
    rows.append(list(rows[0]))                                   # repeated
    rows.append(["", "", "", "Upwork", "bd@mbs.co", "2026-07-01"])  # unusable
    rows.append(["Acme", "Analyst", "", "Upwork", "", ""])       # usable, no link

    report = upload(client, mine, ayesha["id"], sheet(rows))

    buckets = ("added", "known", "duplicate", "repeated", "not_applied", "unusable")
    assert sum(report[key] for key in buckets) == report["rows"] == 9
    assert report["repeated"] == 1
    assert report["unusable"] == 1
    assert report["added"] == 7   # the six, and the one identified by name alone


def test_the_date_column_drives_the_date_window(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    rows = job_rows(2)
    rows[0][5] = "2026-01-05"
    rows[1][5] = "2026-08-20"
    upload(client, mine, ayesha["id"], sheet(rows))

    narrowed = client.get(f"/profiles/{ayesha['id']}/own", headers=mine,
                          params={"since": "2026-08-01", "until": "2026-08-31"}).json()
    assert len(narrowed) == 1
    assert narrowed[0]["applied_on"] == "2026-08-20"


# --------------------------------------------------------------------------- #
# The 250 that never arrived
# --------------------------------------------------------------------------- #

def test_the_same_sheet_twice_adds_nothing_the_second_time(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    data = sheet(job_rows(20))

    first = upload(client, mine, ayesha["id"], data)
    second = upload(client, mine, ayesha["id"], data)

    assert first["added"] == 20
    assert second["added"] == 0
    assert second["duplicate"] == 20
    # And it says so rather than leaving somebody wondering.
    assert second["same_file_as"]
    assert len(client.get(f"/profiles/{ayesha['id']}/own", headers=mine).json()) == 20


def test_a_second_upload_adds_only_the_lines_that_are_missing(client, manager):
    """The 3,000-line sheet where 250 did not make it the first time."""
    (mine, ayesha), _ = workspace(client, manager)

    # Whatever happened — a dropped connection, a half-finished run — only the
    # first 30 of the 40 are on record.
    upload(client, mine, ayesha["id"], sheet(job_rows(30)), "partial.xlsx")

    whole = upload(client, mine, ayesha["id"], sheet(job_rows(40)), "whole.xlsx")

    assert whole["rows"] == 40
    assert whole["duplicate"] == 30   # already on this profile — left alone
    assert whole["added"] == 10       # exactly the ones that were missing
    assert len(client.get(f"/profiles/{ayesha['id']}/own", headers=mine).json()) == 40


def test_a_posting_a_colleague_already_found_is_joined_not_duplicated(client, manager):
    (mine, ayesha), (theirs, bilal) = workspace(client, manager)
    link = "https://www.linkedin.com/jobs/view/3912000001"
    log(client, theirs, bilal["id"], company="Northwind", title="Engineer", url=link)

    report = upload(client, mine, ayesha["id"], sheet(job_rows(3)))

    assert report["known"] == 1       # the posting was already in the pool
    assert report["added"] == 2
    pool = client.get("/jobs", headers=manager).json()
    assert len(pool) == 3             # one row for the posting, not two


def test_a_link_pasted_with_a_tracking_tail_is_the_same_posting(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    upload(client, mine, ayesha["id"], sheet(job_rows(1)))

    again = sheet([["Northwind 1", "Engineer 1",
                    "https://www.linkedin.com/jobs/view/3912000001"
                    "?refId=abc&trackingId=xyz",
                    "LinkedIn", "bd@mbs.co", "2026-07-14"]])
    report = upload(client, mine, ayesha["id"], again)

    assert report["duplicate"] == 1
    assert report["added"] == 0


# --------------------------------------------------------------------------- #
# Sheets people actually keep
# --------------------------------------------------------------------------- #

def test_headings_people_really_type_are_understood(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    data = sheet(
        [["Acme Corp", "Data Engineer", "https://acme.example.com/careers/778899",
          "Upwork", "bd@mbs.co", "14/07/2026"]],
        headers=["Client", "Role", "Link", "Portal", "Applied from", "Applied on"])

    report = upload(client, mine, ayesha["id"], data)

    assert report["added"] == 1
    own = client.get(f"/profiles/{ayesha['id']}/own", headers=mine).json()
    assert own[0]["company"] == "Acme Corp"
    assert own[0]["platform"] == "Upwork"
    # Settled to one spelling on the way in, so every screen reads one day.
    assert own[0]["applied_on"] == "2026-07-14"


def test_a_header_row_that_is_not_the_first_row_is_found(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    data = sheet(job_rows(4), lead_in=[
        ["Ayesha — job tracker"], [], ["Q3 2026"], []])

    assert upload(client, mine, ayesha["id"], data)["added"] == 4


def test_columns_in_any_order_with_extra_ones_alongside(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    data = sheet(
        [["2026-06-02", "notes nobody asked for", "Data Engineer",
          "https://acme.example.com/careers/112233", "Acme"]],
        headers=["Date", "Comments", "Job Title", "Job Link", "Company"])

    assert upload(client, mine, ayesha["id"], data)["added"] == 1
    own = client.get(f"/profiles/{ayesha['id']}/own", headers=mine).json()
    assert own[0]["company"] == "Acme"
    assert own[0]["applied_on"] == "2026-06-02"


def test_a_real_excel_date_comes_out_as_a_day_not_a_timestamp(client, manager):
    from datetime import datetime

    (mine, ayesha), _ = workspace(client, manager)
    data = sheet([["Acme", "Engineer", "https://acme.example.com/careers/445566",
                   "Upwork", "bd@mbs.co", datetime(2026, 6, 2, 0, 0)]])
    upload(client, mine, ayesha["id"], data)

    own = client.get(f"/profiles/{ayesha['id']}/own", headers=mine).json()
    assert own[0]["applied_on"] == "2026-06-02"


def test_a_csv_is_read_the_same_way(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    csv_text = ("Company name,Job title,Job link,Job platform,Email,Date\r\n"
                "Acme,Engineer,https://acme.example.com/careers/998877,"
                "Upwork,bd@mbs.co,2026-05-04\r\n")
    report = upload(client, mine, ayesha["id"],
                    csv_text.encode("utf-8-sig"), "old sheet.csv")

    assert report["rows"] == 1
    assert report["added"] == 1


def test_a_link_hidden_behind_the_word_apply_is_still_read(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    book = Workbook()
    page = book.active
    page.append(MBS_HEADERS)
    page.append(["Acme", "Engineer", "Apply", "Upwork", "bd@mbs.co", "2026-05-04"])
    page.cell(row=2, column=3).hyperlink = "https://acme.example.com/careers/246810"
    stream = io.BytesIO()
    book.save(stream)

    upload(client, mine, ayesha["id"], stream.getvalue())

    own = client.get(f"/profiles/{ayesha['id']}/own", headers=mine).json()
    assert own[0]["url"] == "https://acme.example.com/careers/246810"


def test_a_status_column_never_holds_a_line_back(client, manager):
    """Every line of an uploaded sheet is an application — Skipped, Pending
    and Not applied included. A line withheld is data missed."""
    (mine, ayesha), (theirs, bilal) = workspace(client, manager)
    rows = [["Acme", "Engineer", f"https://acme.example.com/careers/{300 + n}",
             "Upwork", "bd@mbs.co", "2026-05-04", state]
            for n, state in enumerate(("Skipped", "skip", "Pending",
                                       "Not applied", "not yet", "To apply"))]

    report = upload(client, mine, ayesha["id"], sheet(
        rows, headers=MBS_HEADERS + ["Status"]))

    assert report["added"] == 6
    assert report["not_applied"] == 0
    assert report["left_over"] == 0
    assert len(client.get(f"/profiles/{ayesha['id']}/own", headers=mine).json()) == 6


def test_a_status_describing_what_happened_after_applying_still_goes_in(client, manager):
    """"Rejected" means they applied and were turned down. Withholding those
    rows would be the exact thing this feature exists to stop."""
    (mine, ayesha), _ = workspace(client, manager)
    rows = [["Acme", "Engineer", "https://acme.example.com/careers/111", "Upwork",
             "bd@mbs.co", "2026-05-04", state]
            for state in ("Rejected", "No reply", "Interview", "")]
    for index, row in enumerate(rows):
        row[2] = f"https://acme.example.com/careers/{index + 100}"

    report = upload(client, mine, ayesha["id"], sheet(
        rows, headers=MBS_HEADERS + ["Status"]))

    assert report["added"] == 4
    assert report["not_applied"] == 0


def test_an_ambiguous_status_does_not_hold_a_line_back(client, manager):
    """"No" and "N/A" are as likely to mean "no reply" as "not applied", and a
    row withheld is the one failure this feature exists to prevent."""
    (mine, ayesha), _ = workspace(client, manager)
    rows = [["Acme", "Engineer", f"https://acme.example.com/careers/{200 + n}",
             "Upwork", "bd@mbs.co", "2026-05-04", state]
            for n, state in enumerate(("No", "None", "N/A", "-", "?"))]

    report = upload(client, mine, ayesha["id"], sheet(
        rows, headers=MBS_HEADERS + ["Status"]))

    assert report["added"] == 5
    assert report["not_applied"] == 0


# --------------------------------------------------------------------------- #
# A sheet lined up against the team's Google Sheet
# --------------------------------------------------------------------------- #

def google_row(n, applied_on="2026-07-14", **over):
    row = {"Applied on": applied_on, "BD": "Ayesha", "Company name": f"Acme {n}",
           "Job title": f"Engineer {n}",
           "Job link": f"https://www.linkedin.com/jobs/view/39130000{n:02d}",
           "Job platform": "LinkedIn", "Email": "bd@mbs.co",
           "Own or others": "Own job", "Found by": "Ayesha",
           "Filed at": "2026-07-14 10:30:00"}
    row.update(over)
    return [row[h] for h in GOOGLE_HEADERS]


def test_a_sheet_in_the_google_sheets_columns_goes_in_whole(client, manager):
    (mine, ayesha), (theirs, bilal) = workspace(client, manager)
    data = sheet([google_row(n) for n in range(1, 6)], headers=GOOGLE_HEADERS)

    report = upload(client, mine, ayesha["id"], data)

    assert report["added"] == 5
    assert report["undated"] == 0
    own = client.get(f"/profiles/{ayesha['id']}/own", headers=mine).json()
    assert {row["company"] for row in own} == {f"Acme {n}" for n in range(1, 6)}
    assert all(row["applied_on"] == "2026-07-14" for row in own)
    assert all(row["email"] == "bd@mbs.co" and row["platform"] == "LinkedIn"
               for row in own)

    # All jobs carries every line, standing as this profile's own application.
    pool = client.get(f"/profiles/{ayesha['id']}/all", headers=mine).json()
    assert sorted(row["standing"] for row in pool) == ["own"] * 5
    pending = client.get(f"/profiles/{bilal['id']}/others", headers=theirs,
                         params={"status": "pending"}).json()
    assert len(pending) == 5


def test_a_blank_applied_on_falls_back_to_filed_at(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    data = sheet([google_row(1, applied_on="", **{"Filed at": "2026-06-30 09:00:00"})],
                 headers=GOOGLE_HEADERS)

    report = upload(client, mine, ayesha["id"], data)

    assert report["undated"] == 0
    own = client.get(f"/profiles/{ayesha['id']}/own", headers=mine).json()
    assert own[0]["applied_on"] == "2026-06-30"


def test_a_whole_downloaded_workbook_reads_only_this_profiles_tab(client, manager):
    """The team's file has a tab per profile. Uploading all of it must not file
    every colleague's work under this one."""
    (mine, ayesha), _ = workspace(client, manager)
    book = Workbook()
    book.remove(book.active)
    for name, first in ((ayesha["name"], 1), ("Bilal — Engineer", 20)):
        page = book.create_sheet(name[:31])
        page.append(GOOGLE_HEADERS)
        for n in range(first, first + 3):
            page.append(google_row(n))
    stream = io.BytesIO()
    book.save(stream)

    report = upload(client, mine, ayesha["id"], stream.getvalue())

    assert report["rows"] == 3
    assert report["added"] == 3
    assert report["sheets"] == ayesha["name"]


def test_a_workbook_split_by_month_is_read_whole(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    book = Workbook()
    book.remove(book.active)
    for month, first in (("July", 1), ("August", 10)):
        page = book.create_sheet(month)
        page.append(GOOGLE_HEADERS)
        for n in range(first, first + 2):
            page.append(google_row(n))
    stream = io.BytesIO()
    book.save(stream)

    assert upload(client, mine, ayesha["id"], stream.getvalue())["added"] == 4


def test_a_month_first_file_is_read_month_first(client, manager):
    """07/14/2026 can only be month-first, so 03/04/2026 in the same file is
    the 4th of March, not the 3rd of April."""
    (mine, ayesha), _ = workspace(client, manager)
    data = sheet([google_row(1, applied_on="07/14/2026"),
                  google_row(2, applied_on="03/04/2026")], headers=GOOGLE_HEADERS)
    upload(client, mine, ayesha["id"], data)

    days = {row["company"]: row["applied_on"] for row in
            client.get(f"/profiles/{ayesha['id']}/own", headers=mine).json()}
    assert days == {"Acme 1": "2026-07-14", "Acme 2": "2026-03-04"}


def test_date_spellings_are_settled_to_one_day(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    spellings = ["14/07/2026", "14-Jul-2026", "Jul 14, 2026", "2026-07-14 18:05",
                 "46217"]   # the last is 2026-07-14 as an Excel day count
    data = sheet([google_row(n, applied_on=typed)
                  for n, typed in enumerate(spellings, start=1)],
                 headers=GOOGLE_HEADERS)
    report = upload(client, mine, ayesha["id"], data)

    assert report["undated"] == 0
    own = client.get(f"/profiles/{ayesha['id']}/own", headers=mine).json()
    assert {row["applied_on"] for row in own} == {"2026-07-14"}


def test_an_unreadable_date_still_goes_in_and_is_reported(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    data = sheet([google_row(1, applied_on="sometime in July", **{"Filed at": ""})],
                 headers=GOOGLE_HEADERS)

    report = upload(client, mine, ayesha["id"], data)

    assert report["added"] == 1
    assert report["undated"] == 1

    # Fixed and uploaded again: the line gets its day, and is not doubled.
    fixed = sheet([google_row(1, applied_on="2026-07-02")], headers=GOOGLE_HEADERS)
    again = upload(client, mine, ayesha["id"], fixed)
    assert again["duplicate"] == 1
    own = client.get(f"/profiles/{ayesha['id']}/own", headers=mine).json()
    assert len(own) == 1
    assert own[0]["applied_on"] == "2026-07-02"


def test_an_imported_line_closes_off_a_job_this_profile_had_skipped(client, manager):
    """The sheet says it was applied for. Leaving it on the Skipped list too
    would count one job twice, in two contradictory places."""
    (mine, ayesha), (theirs, bilal) = workspace(client, manager)
    url = "https://www.linkedin.com/jobs/view/3913000001"
    log(client, theirs, bilal["id"], company="Acme 1", title="Engineer 1", url=url)
    handed = client.get(f"/profiles/{ayesha['id']}/others", headers=mine,
                        params={"status": "pending"}).json()[0]
    reply = client.post(f"/assignments/{handed['assignment_id']}", headers=mine,
                         json={"status": "skipped", "reason": "not a fit"})
    assert reply.status_code == 200, reply.text

    report = upload(client, mine, ayesha["id"],
                    sheet([google_row(1)], headers=GOOGLE_HEADERS))

    assert report["known"] == 1
    assert client.get(f"/profiles/{ayesha['id']}/others", headers=mine,
                      params={"status": "skipped"}).json() == []
    pool = client.get(f"/profiles/{ayesha['id']}/all", headers=mine).json()
    assert pool[0]["standing"] == "own"


# --------------------------------------------------------------------------- #
# What could not go in
# --------------------------------------------------------------------------- #

def test_the_lines_that_did_not_go_in_come_back_as_a_sheet(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    rows = job_rows(3)
    rows.append(["", "", "", "Upwork", "bd@mbs.co", "2026-07-01"])

    report = upload(client, mine, ayesha["id"], sheet(rows))
    assert report["left_over"] == 1

    reply = client.get(f"/imports/{report['id']}/leftovers.xlsx", headers=mine)
    assert reply.status_code == 200
    book = load_workbook(io.BytesIO(reply.content))
    page = book["Left over"]
    assert page.max_row == 2                       # the header and the one line
    assert page.cell(row=2, column=2).value == 5   # the row number in the sheet
    assert "identified" in page.cell(row=2, column=3).value


def test_nothing_left_over_means_nothing_to_download(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    report = upload(client, mine, ayesha["id"], sheet(job_rows(2)))
    assert client.get(f"/imports/{report['id']}/leftovers.xlsx",
                      headers=mine).status_code == 404


def test_a_file_that_is_not_a_sheet_is_refused_before_anything_is_written(
        client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    reply = client.post(f"/profiles/{ayesha['id']}/import", headers=mine,
                        files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")})
    assert reply.status_code == 400
    assert ".xlsx" in reply.json()["detail"]
    assert client.get(f"/profiles/{ayesha['id']}/imports", headers=mine).json() == []


def test_a_sheet_with_no_recognisable_headings_says_so(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    data = sheet([["a", "b", "c"]], headers=["alpha", "beta", "gamma"])
    reply = client.post(f"/profiles/{ayesha['id']}/import", headers=mine,
                        files={"file": ("mystery.xlsx", data, "application/xlsx")})
    assert reply.status_code == 400
    assert "headings" in reply.json()["detail"]


# --------------------------------------------------------------------------- #
# The record of it
# --------------------------------------------------------------------------- #

def test_the_history_keeps_every_upload_newest_first(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    upload(client, mine, ayesha["id"], sheet(job_rows(2)), "january.xlsx")
    upload(client, mine, ayesha["id"], sheet(job_rows(2, start=50)), "february.xlsx")

    history = client.get(f"/profiles/{ayesha['id']}/imports", headers=mine).json()
    assert [row["filename"] for row in history] == ["february.xlsx", "january.xlsx"]
    assert history[0]["by"] == "Ayesha"
    assert history[0]["sheets"] == "Jobs"


def test_a_bd_cannot_upload_against_somebody_elses_profile(client, manager):
    (mine, ayesha), (theirs, bilal) = workspace(client, manager)
    reply = client.post(f"/profiles/{bilal['id']}/import", headers=mine,
                        files={"file": ("x.xlsx", sheet(job_rows(1)), "application/xlsx")})
    assert reply.status_code == 403


def test_a_manager_reads_the_history_but_does_not_file_the_work(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    upload(client, mine, ayesha["id"], sheet(job_rows(2)))

    assert len(client.get(f"/profiles/{ayesha['id']}/imports",
                          headers=manager).json()) == 1
    refused = client.post(f"/profiles/{ayesha['id']}/import", headers=manager,
                          files={"file": ("x.xlsx", sheet(job_rows(1)),
                                          "application/xlsx")})
    assert refused.status_code == 403


def test_deleting_a_profile_takes_its_uploads_with_it(client, manager):
    (mine, ayesha), _ = workspace(client, manager)
    rows = job_rows(2) + [["", "", "", "Upwork", "bd@mbs.co", "2026-07-01"]]
    report = upload(client, mine, ayesha["id"], sheet(rows))
    assert report["left_over"] == 1
    assert client.get(f"/imports/{report['id']}/leftovers.xlsx",
                      headers=mine).status_code == 200

    assert client.delete(f"/profiles/{ayesha['id']}", headers=manager).status_code == 200
    assert client.get(f"/imports/{report['id']}/leftovers.xlsx",
                      headers=manager).status_code == 404


# --------------------------------------------------------------------------- #
# The template
# --------------------------------------------------------------------------- #

def test_the_template_carries_the_six_columns_the_grid_asks_for(client, manager):
    reply = client.get("/import-template.xlsx", headers=manager)
    assert reply.status_code == 200

    book = load_workbook(io.BytesIO(reply.content))
    assert [cell.value for cell in book["Jobs"][1]] == GOOGLE_HEADERS[:1] + \
        GOOGLE_HEADERS[2:7]
    assert book["Jobs"].max_row == 1          # headings, and nothing under them
    assert "How this is read" in book.sheetnames


def test_an_untouched_template_files_nothing(client, manager):
    """Its explanations must not read back as rows, and its example must be
    somewhere it can be read rather than somewhere it can be imported."""
    (mine, ayesha), _ = workspace(client, manager)
    template = client.get("/import-template.xlsx", headers=mine).content

    reply = client.post(f"/profiles/{ayesha['id']}/import", headers=mine,
                        files={"file": ("MBS import template.xlsx", template,
                                        "application/xlsx")})
    # No data rows at all, so it is refused the same way a blank sheet is —
    # and nothing fictional lands on anybody's list.
    assert reply.status_code == 400
    assert client.get(f"/profiles/{ayesha['id']}/own", headers=mine).json() == []


def test_the_template_fills_in_and_uploads(client, manager):
    """A template whose own headings will not import is a broken template."""
    (mine, ayesha), _ = workspace(client, manager)
    template = client.get("/import-template.xlsx", headers=mine).content

    book = load_workbook(io.BytesIO(template))
    for row in job_rows(3):
        book["Jobs"].append(row)
    stream = io.BytesIO()
    book.save(stream)

    assert upload(client, mine, ayesha["id"], stream.getvalue(),
                  "my jobs.xlsx")["added"] == 3
