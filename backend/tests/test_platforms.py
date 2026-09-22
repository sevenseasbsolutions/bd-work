"""The job-platform list the manager keeps, and the entry grid types against."""
from conftest import sign_in
from helpers import log, make_bd, make_profile


def names(client, headers):
    return [row["name"] for row in client.get("/platforms", headers=headers).json()]


def test_a_new_workspace_starts_with_a_list_to_work_from(client, manager):
    assert "Upwork" in names(client, manager)
    assert "LinkedIn" in names(client, manager)


def test_a_manager_adds_one(client, manager):
    reply = client.post("/platforms", headers=manager, json={"name": "Toptal"})
    assert reply.status_code == 201
    assert "Toptal" in names(client, manager)


def test_the_same_board_cannot_be_added_twice(client, manager):
    assert client.post("/platforms", headers=manager,
                       json={"name": "upwork"}).status_code == 409


def test_a_bd_reads_the_list_but_cannot_change_it(client, manager):
    make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    bd = sign_in(client, "ayesha@mbs.co", "secret")

    # They need it — it fills the dropdown on their own entry grid.
    assert "Upwork" in names(client, bd)
    assert client.post("/platforms", headers=bd,
                       json={"name": "Sneaky"}).status_code == 403


def test_deleting_a_board_leaves_the_jobs_recorded_against_it_alone(client, manager):
    """A job keeps the text that was chosen, not a reference to the row."""
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    headers = sign_in(client, "ayesha@mbs.co", "secret")
    profile = make_profile(client, manager, "Khuram", bd["id"])
    log(client, headers, profile["id"], company="Northwind", title="RAG Engineer",
        platform="Upwork", url="https://www.upwork.com/jobs/~017acdef99120abc44")

    upwork = next(p for p in client.get("/platforms", headers=manager).json()
                  if p["name"] == "Upwork")
    reply = client.delete(f"/platforms/{upwork['id']}", headers=manager)
    assert reply.json()["jobs_keeping_it"] == 1

    assert "Upwork" not in names(client, manager)
    assert client.get("/jobs", headers=manager).json()[0]["platform"] == "Upwork"


def test_a_board_the_manager_deleted_does_not_come_back_on_reboot(client, manager):
    """Seeding only fills an empty table, so a deletion is a decision."""
    from app.main import boot

    other = next(p for p in client.get("/platforms", headers=manager).json()
                 if p["name"] == "Other")
    client.delete(f"/platforms/{other['id']}", headers=manager)
    boot()
    assert "Other" not in names(client, manager)
