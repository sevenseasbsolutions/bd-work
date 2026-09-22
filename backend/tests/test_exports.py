"""The workbooks: what a BD and a manager can send on to somebody else."""
import io

from conftest import sign_in
from helpers import log, make_bd, make_profile
from openpyxl import load_workbook

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def opened(reply):
    assert reply.status_code == 200, reply.text
    assert reply.headers["content-type"].startswith(XLSX)
    return load_workbook(io.BytesIO(reply.content))


def cells(page):
    """Every row as a list, header included."""
    return [[cell for cell in row] for row in page.iter_rows(values_only=True)]


def a_profile_with_work(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    headers = sign_in(client, "ayesha@mbs.co", "secret")
    finder = make_profile(client, manager, "Khuram — AI Engineer", bd["id"],
                          headline="AI / LLM Engineer", platform="Upwork")
    other = make_profile(client, manager, "Zahid", bd["id"])

    log(client, headers, finder["id"], company="Northwind Labs",
        title="Senior RAG Engineer", platform="Upwork",
        url="https://www.upwork.com/jobs/~017acdef99120abc44",
        email="khuram.apply@mbs.co", applied_on="2026-09-14")
    log(client, headers, finder["id"], company="Bluepeak AI",
        title="LLM Fine-tuning Specialist", platform="Upwork",
        url="https://www.upwork.com/jobs/~011bb2299ffee33001",
        email="khuram.apply@mbs.co", applied_on="2026-09-16")
    return headers, finder, other


# --------------------------------------------------------------------------- #
# A BD's own profile
# --------------------------------------------------------------------------- #

def test_a_profile_exports_its_three_lists_and_its_counts(client, manager):
    headers, finder, _other = a_profile_with_work(client, manager)
    book = opened(client.get(f"/profiles/{finder['id']}/export.xlsx", headers=headers))

    assert book.sheetnames == ["Summary", "Own jobs", "Others' jobs", "All jobs"]

    summary = dict(row[:2] for row in cells(book["Summary"]) if row[0])
    assert summary["Own jobs"] == 2
    assert summary["Applied in all"] == 2
    assert summary["Date range"] == "All time"

    own = cells(book["Own jobs"])
    assert own[0] == ["Company name", "Job title", "Job link", "Job platform",
                      "Email", "Date", "Also applied"]
    assert len(own) == 3  # the header plus the two finds
    assert own[1][0] == "Bluepeak AI"            # newest first, as on the screen
    assert own[1][4] == "khuram.apply@mbs.co"
    assert own[1][5] == "2026-09-16"


def test_the_link_column_is_a_real_hyperlink(client, manager):
    """Blue text nobody can click is not a link."""
    headers, finder, _other = a_profile_with_work(client, manager)
    book = opened(client.get(f"/profiles/{finder['id']}/export.xlsx", headers=headers))
    cell = book["Own jobs"]["C2"]
    assert cell.value.startswith("https://")
    assert cell.hyperlink.target == cell.value


def test_the_others_jobs_sheet_holds_all_three_statuses(client, manager):
    headers, _finder, other = a_profile_with_work(client, manager)
    handed = client.get(f"/profiles/{other['id']}/others", headers=headers).json()
    client.post(f"/assignments/{handed[0]['assignment_id']}", headers=headers,
                json={"status": "applied"})
    client.post(f"/assignments/{handed[1]['assignment_id']}", headers=headers,
                json={"status": "skipped"})

    book = opened(client.get(f"/profiles/{other['id']}/export.xlsx", headers=headers))
    rows = cells(book["Others' jobs"])
    assert sorted(row[5] for row in rows[1:]) == ["Applied", "Skipped"]


def test_an_export_is_read_through_the_same_window_as_the_screen(client, manager):
    headers, finder, _other = a_profile_with_work(client, manager)
    url = f"/profiles/{finder['id']}/export.xlsx?since=2026-09-15"

    book = opened(client.get(url, headers=headers))
    summary = dict(row[:2] for row in cells(book["Summary"]) if row[0])
    assert summary["Own jobs"] == 1
    assert summary["Date range"] == "from 2026-09-15"
    assert len(cells(book["Own jobs"])) == 2  # header plus the one inside the window


def test_the_filename_survives_a_profile_name_with_an_em_dash(client, manager):
    """A raw em dash in a header is a parse error, not a download."""
    headers, finder, _other = a_profile_with_work(client, manager)
    reply = client.get(f"/profiles/{finder['id']}/export.xlsx", headers=headers)
    disposition = reply.headers["content-disposition"]

    assert disposition.isascii()
    assert "filename*=UTF-8''" in disposition
    assert "Khuram" in disposition and ".xlsx" in disposition


# --------------------------------------------------------------------------- #
# The manager's workspace
# --------------------------------------------------------------------------- #

def test_the_workspace_export_carries_every_screen(client, manager):
    a_profile_with_work(client, manager)
    book = opened(client.get("/export.xlsx", headers=manager))

    assert book.sheetnames == ["Summary", "By BD", "By profile", "By day",
                               "All jobs", "People"]

    summary = dict(row[:2] for row in cells(book["Summary"]) if row[0])
    assert summary["Own jobs found"] == 2
    assert summary["Jobs in the pool"] == 2
    assert summary["Profiles"] == 2

    seats = cells(book["By BD"])
    assert seats[0][0] == "BD" and seats[1][0] == "Ayesha"
    assert seats[1][2] == 2                       # both finds are hers

    people = cells(book["People"])
    assert {row[2] for row in people[1:]} == {"manager", "bd"}


def test_the_workspace_export_narrows_with_the_window(client, manager):
    a_profile_with_work(client, manager)
    book = opened(client.get("/export.xlsx?since=2026-09-15", headers=manager))
    summary = dict(row[:2] for row in cells(book["Summary"]) if row[0])
    assert summary["Own jobs found"] == 1
    assert summary["Date range"] == "from 2026-09-15"


# --------------------------------------------------------------------------- #
# Who can export what
# --------------------------------------------------------------------------- #

def test_a_bd_cannot_export_the_workspace(client, manager):
    make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    bd = sign_in(client, "ayesha@mbs.co", "secret")
    assert client.get("/export.xlsx", headers=bd).status_code == 403


def test_a_bd_cannot_export_somebody_elses_profile(client, manager):
    _headers, finder, _other = a_profile_with_work(client, manager)
    make_bd(client, manager, "Bilal", "bilal@mbs.co")
    his = sign_in(client, "bilal@mbs.co", "secret")
    assert client.get(f"/profiles/{finder['id']}/export.xlsx",
                      headers=his).status_code == 403


def test_a_manager_can_export_any_profile(client, manager):
    _headers, finder, _other = a_profile_with_work(client, manager)
    book = opened(client.get(f"/profiles/{finder['id']}/export.xlsx", headers=manager))
    assert len(cells(book["Own jobs"])) == 3


def test_signing_out_takes_the_export_with_it(client):
    assert client.get("/export.xlsx").status_code == 401
