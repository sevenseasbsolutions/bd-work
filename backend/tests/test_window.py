"""The date range: from this day to that day, on every screen at once."""
from datetime import datetime

import pytest
from conftest import sign_in

from app.dispatch import as_date, within
from helpers import log, make_bd, make_profile

FILED = datetime(2026, 9, 16, 11, 30)


# --------------------------------------------------------------------------- #
# Reading the date somebody typed
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("typed, expected", [
    ("2026-09-14", "2026-09-14"),
    ("14/09/2026", "2026-09-14"),
    ("2026/09/14", "2026-09-14"),
    ("14 Sep 2026", "2026-09-14"),
    ("14 September 2026", "2026-09-14"),
    ("Sep 14, 2026", "2026-09-14"),
])
def test_the_shapes_people_actually_type_are_all_read(typed, expected):
    assert str(as_date(typed, FILED)) == expected


def test_a_date_with_no_year_means_this_year_not_1900():
    # Left to strptime this is 1900-09-14, which drops the row out of every
    # window there is.
    assert str(as_date("14 Sep", FILED)) == "2026-09-14"


def test_something_unreadable_falls_back_to_when_it_was_filed():
    assert str(as_date("last tuesday-ish", FILED)) == "2026-09-16"
    assert str(as_date("", FILED)) == "2026-09-16"


def test_no_window_means_everything_including_rows_with_no_date():
    assert within(None, None, None) is True
    assert within(FILED.date(), None, None) is True


def test_a_row_with_no_date_is_left_out_of_a_window():
    """Counting it anyway would make a filtered total larger than it is."""
    assert within(None, FILED.date(), None) is False


# --------------------------------------------------------------------------- #
# Through the API
# --------------------------------------------------------------------------- #

def three_days_of_work(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    headers = sign_in(client, "ayesha@mbs.co", "secret")
    profile = make_profile(client, manager, "Khuram", bd["id"])
    for day, title in [("2026-09-10", "Monday find"),
                       ("2026-09-14", "Friday find"),
                       ("2026-09-16", "Sunday find")]:
        log(client, headers, profile["id"], company="Northwind", title=title,
            url=f"https://www.linkedin.com/jobs/view/40000000{day[-2:]}",
            applied_on=day)
    return headers, profile


def titles(reply):
    return sorted(row["title"] for row in reply.json())


def test_own_jobs_narrows_to_the_window(client, manager):
    headers, profile = three_days_of_work(client, manager)
    url = f"/profiles/{profile['id']}/own"

    assert len(titles(client.get(url, headers=headers))) == 3
    assert titles(client.get(url + "?since=2026-09-14", headers=headers)) \
        == ["Friday find", "Sunday find"]
    assert titles(client.get(url + "?until=2026-09-14", headers=headers)) \
        == ["Friday find", "Monday find"]
    assert titles(client.get(url + "?since=2026-09-12&until=2026-09-15",
                             headers=headers)) == ["Friday find"]


def test_both_ends_are_inclusive(client, manager):
    headers, profile = three_days_of_work(client, manager)
    reply = client.get(f"/profiles/{profile['id']}/own?since=2026-09-10&until=2026-09-10",
                       headers=headers)
    assert titles(reply) == ["Monday find"]


def test_the_counts_move_with_the_list(client, manager):
    """The tiles above a list and the list itself read the same window."""
    headers, profile = three_days_of_work(client, manager)
    span = "?since=2026-09-12&until=2026-09-15"

    listed = client.get(f"/profiles/{profile['id']}/own{span}", headers=headers).json()
    counted = client.get(f"/profiles{span}", headers=headers).json()[0]["counts"]
    assert len(listed) == counted["own"] == 1

    board = client.get(f"/overview{span}", headers=manager).json()
    assert board["totals"]["own"] == 1
    assert board["people"][0]["own"] == 1


def test_the_pool_narrows_by_when_a_posting_was_first_seen(client, manager):
    """Everything here was found today, so yesterday holds nothing."""
    three_days_of_work(client, manager)
    assert len(client.get("/jobs", headers=manager).json()) == 3
    assert client.get("/jobs?until=2020-01-01", headers=manager).json() == []


def test_a_date_that_is_not_a_date_is_refused_rather_than_ignored(client, manager):
    headers, profile = three_days_of_work(client, manager)
    bad = client.get(f"/profiles/{profile['id']}/own?since=last-week", headers=headers)
    assert bad.status_code == 400
    assert "YYYY-MM-DD" in bad.json()["detail"]
