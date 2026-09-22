"""Select all, and the switch the manager keeps it behind.

Three months of somebody's sheet arriving in the pool is three months of
others' jobs arriving on everybody else's list. Either there is a way through
them in one press or the import is a gift nobody wanted.
"""
from __future__ import annotations

from helpers import log, make_bd, make_profile
from conftest import sign_in


def team(client, manager):
    """A finder and a colleague, with a profile each."""
    finder = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    other = make_bd(client, manager, "Bilal", "bilal@mbs.co")
    mine = make_profile(client, manager, "Ayesha — Engineer", finder["id"])
    theirs = make_profile(client, manager, "Bilal — Engineer", other["id"])
    return (sign_in(client, "ayesha@mbs.co", "secret"), mine,
            sign_in(client, "bilal@mbs.co", "secret"), theirs)


def dispatch_jobs(client, headers, profile_id, count):
    for n in range(count):
        log(client, headers, profile_id, company=f"Northwind {n}",
            title=f"Engineer {n}",
            url=f"https://www.linkedin.com/jobs/view/391200{n:04d}")


def pending_ids(client, headers, profile_id):
    rows = client.get(f"/profiles/{profile_id}/others", headers=headers,
                      params={"status": "pending"}).json()
    return [row["assignment_id"] for row in rows]


# --------------------------------------------------------------------------- #
# The button itself
# --------------------------------------------------------------------------- #

def test_skipping_everything_takes_one_request(client, manager):
    mine, ayesha, theirs, bilal = team(client, manager)
    dispatch_jobs(client, mine, ayesha["id"], 8)
    ids = pending_ids(client, theirs, bilal["id"])
    assert len(ids) == 8

    reply = client.post("/assignments/bulk", headers=theirs,
                        json={"ids": ids, "status": "skipped"})
    assert reply.status_code == 200
    assert reply.json() == {"moved": 8, "unchanged": 0, "missing": 0,
                            "status": "skipped"}

    assert pending_ids(client, theirs, bilal["id"]) == []
    skipped = client.get(f"/profiles/{bilal['id']}/others", headers=theirs,
                         params={"status": "skipped"}).json()
    assert len(skipped) == 8


def test_applying_for_everything_writes_the_applications(client, manager):
    mine, ayesha, theirs, bilal = team(client, manager)
    dispatch_jobs(client, mine, ayesha["id"], 5)
    ids = pending_ids(client, theirs, bilal["id"])

    client.post("/assignments/bulk", headers=theirs,
                json={"ids": ids, "status": "applied", "applied_on": "2026-08-01"})

    applied = client.get(f"/profiles/{bilal['id']}/others", headers=theirs,
                         params={"status": "applied"}).json()
    assert len(applied) == 5
    # The counts a manager reads are made of those applications, so they have
    # to move too — a bulk press that changed the list and not the numbers
    # would be the worst kind of half-working.
    board = client.get("/overview", headers=manager).json()
    seat = next(p for p in board["profiles"] if p["id"] == bilal["id"])
    assert seat["counts"]["from_others"] == 5
    assert seat["counts"]["applied"] == 5
    assert seat["counts"]["pending"] == 0


def test_undoing_in_bulk_puts_them_back_and_takes_the_applications_away(
        client, manager):
    mine, ayesha, theirs, bilal = team(client, manager)
    dispatch_jobs(client, mine, ayesha["id"], 4)
    ids = pending_ids(client, theirs, bilal["id"])
    client.post("/assignments/bulk", headers=theirs,
                json={"ids": ids, "status": "applied"})

    client.post("/assignments/bulk", headers=theirs,
                json={"ids": ids, "status": "pending"})

    assert len(pending_ids(client, theirs, bilal["id"])) == 4
    board = client.get("/overview", headers=manager).json()
    seat = next(p for p in board["profiles"] if p["id"] == bilal["id"])
    assert seat["counts"]["from_others"] == 0


def test_rows_already_at_that_status_are_counted_apart_from_the_ones_that_moved(
        client, manager):
    mine, ayesha, theirs, bilal = team(client, manager)
    dispatch_jobs(client, mine, ayesha["id"], 6)
    ids = pending_ids(client, theirs, bilal["id"])
    client.post(f"/assignments/{ids[0]}", headers=theirs, json={"status": "skipped"})

    reply = client.post("/assignments/bulk", headers=theirs,
                        json={"ids": ids, "status": "skipped"}).json()
    assert reply["moved"] == 5
    assert reply["unchanged"] == 1


def test_a_row_that_is_no_longer_there_is_reported_not_guessed_at(client, manager):
    mine, ayesha, theirs, bilal = team(client, manager)
    dispatch_jobs(client, mine, ayesha["id"], 3)
    ids = pending_ids(client, theirs, bilal["id"])

    reply = client.post("/assignments/bulk", headers=theirs,
                        json={"ids": ids + [999999], "status": "skipped"}).json()
    assert reply["moved"] == 3
    assert reply["missing"] == 1


def test_one_row_in_the_list_that_is_not_yours_stops_the_whole_press(client, manager):
    """Not "do the ones you may": a press that silently did four of five rows
    is a press nobody can check afterwards."""
    mine, ayesha, theirs, bilal = team(client, manager)
    dispatch_jobs(client, mine, ayesha["id"], 3)
    theirs_ids = pending_ids(client, theirs, bilal["id"])

    log(client, theirs, bilal["id"], company="Acme", title="Analyst",
        url="https://acme.example.com/careers/778899")
    mine_ids = pending_ids(client, mine, ayesha["id"])

    reply = client.post("/assignments/bulk", headers=theirs,
                        json={"ids": theirs_ids + mine_ids, "status": "skipped"})
    assert reply.status_code == 403
    assert len(pending_ids(client, theirs, bilal["id"])) == 3


def test_a_status_that_is_not_one_of_the_three_is_refused(client, manager):
    mine, ayesha, theirs, bilal = team(client, manager)
    dispatch_jobs(client, mine, ayesha["id"], 2)
    ids = pending_ids(client, theirs, bilal["id"])

    reply = client.post("/assignments/bulk", headers=theirs,
                        json={"ids": ids, "status": "maybe"})
    assert reply.status_code == 400


def test_an_empty_selection_is_not_a_request(client, manager):
    _, _, theirs, _ = team(client, manager)
    assert client.post("/assignments/bulk", headers=theirs,
                       json={"ids": [], "status": "skipped"}).status_code == 422


# --------------------------------------------------------------------------- #
# The switch
# --------------------------------------------------------------------------- #

def test_select_all_starts_on(client, manager):
    # The key, not the whole dict: there is more than one switch now, and a
    # test about this one should not fail when another is added.
    assert client.get("/settings", headers=manager).json()["select_all"] is True


def test_a_bd_reads_the_switch_but_does_not_set_it(client, manager):
    _, _, theirs, _ = team(client, manager)
    assert client.get("/settings", headers=theirs).json()["select_all"] is True
    assert client.patch("/settings", headers=theirs,
                        json={"select_all": False}).status_code == 403


def test_switching_select_all_off_stops_the_bulk_press(client, manager):
    mine, ayesha, theirs, bilal = team(client, manager)
    dispatch_jobs(client, mine, ayesha["id"], 4)
    ids = pending_ids(client, theirs, bilal["id"])

    assert client.patch("/settings", headers=manager,
                        json={"select_all": False}).json()["select_all"] is False

    refused = client.post("/assignments/bulk", headers=theirs,
                          json={"ids": ids, "status": "skipped"})
    assert refused.status_code == 403
    assert "Select all" in refused.json()["detail"]
    # The row buttons are untouched — the switch is about doing it wholesale.
    assert client.post(f"/assignments/{ids[0]}", headers=theirs,
                       json={"status": "skipped"}).status_code == 200
    assert len(pending_ids(client, theirs, bilal["id"])) == 3


def test_switching_it_back_on_lets_the_press_through_again(client, manager):
    mine, ayesha, theirs, bilal = team(client, manager)
    dispatch_jobs(client, mine, ayesha["id"], 4)
    ids = pending_ids(client, theirs, bilal["id"])

    client.patch("/settings", headers=manager, json={"select_all": False})
    client.patch("/settings", headers=manager, json={"select_all": True})

    assert client.post("/assignments/bulk", headers=theirs,
                       json={"ids": ids, "status": "skipped"}).status_code == 200


def test_the_switch_survives_a_restart(client, manager):
    """It is a row in the database, not something held in the process."""
    from app.main import boot

    client.patch("/settings", headers=manager, json={"select_all": False})
    boot()
    assert client.get("/settings", headers=manager).json()["select_all"] is False


def test_a_manager_is_not_locked_out_by_their_own_switch(client, manager):
    """Otherwise turning it off would leave nobody able to clear a mistaken
    import — including the person who turned it off."""
    mine, ayesha, theirs, bilal = team(client, manager)
    dispatch_jobs(client, mine, ayesha["id"], 3)
    ids = pending_ids(client, theirs, bilal["id"])
    client.patch("/settings", headers=manager, json={"select_all": False})

    assert client.post("/assignments/bulk", headers=manager,
                       json={"ids": ids, "status": "skipped"}).status_code == 200


def test_an_unknown_switch_is_not_invented_by_asking_for_it(client, manager):
    reply = client.patch("/settings", headers=manager,
                         json={"select_all": True, "something_else": True})
    assert reply.status_code == 200
    assert reply.json()["select_all"] is True
    # The point of the test: a key nobody declared is neither stored nor
    # handed back, so a typo in a PATCH cannot grow the settings table.
    assert "something_else" not in reply.json()


# --------------------------------------------------------------------------- #
# The two halves together
# --------------------------------------------------------------------------- #

def test_a_whole_imported_sheet_can_be_cleared_in_one_press(client, manager):
    """The case the feature exists for: a colleague uploads three months of
    work, and everybody else clears the pile it made in one go."""
    import test_imports as sheets

    mine, ayesha, theirs, bilal = team(client, manager)
    sheets.upload(client, mine, ayesha["id"], sheets.sheet(sheets.job_rows(60)))

    ids = pending_ids(client, theirs, bilal["id"])
    assert len(ids) == 60

    assert client.post("/assignments/bulk", headers=theirs,
                       json={"ids": ids, "status": "skipped"}).json()["moved"] == 60
    assert pending_ids(client, theirs, bilal["id"]) == []
