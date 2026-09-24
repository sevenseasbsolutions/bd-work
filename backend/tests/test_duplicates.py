"""Applying twice, on purpose or not, and saying why a job was turned down.

The entry grid asks first (/own/check) and files second (/own); the two match
lines the same way, so "you already applied" and "duplicate" never disagree.
Also here: the reason kept on a skip, and a manager editing somebody's email
and role.
"""
import re

from conftest import sign_in
from helpers import log, make_bd, make_profile

URL = "https://www.upwork.com/jobs/~017acdef99120abc44"
JOB = {"title": "RAG Engineer", "company": "Northwind", "url": URL}


def one_bd_two_profiles(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    headers = sign_in(client, "ayesha@mbs.co", "secret")
    khuram = make_profile(client, manager, "Khuram", bd["id"])
    zahid = make_profile(client, manager, "Zahid", bd["id"])
    return headers, bd, khuram, zahid


def check(client, headers, profile_id, *jobs):
    reply = client.post(f"/profiles/{profile_id}/own/check", headers=headers,
                        json={"jobs": list(jobs)})
    assert reply.status_code == 200, reply.text
    return reply.json()


def own(client, headers, profile_id):
    return client.get(f"/profiles/{profile_id}/own", headers=headers).json()


# --------------------------------------------------------------------------- #
# Asking before filing
# --------------------------------------------------------------------------- #

def test_check_says_where_and_when_this_bd_applied(client, manager):
    headers, _bd, khuram, zahid = one_bd_two_profiles(client, manager)
    log(client, headers, khuram["id"], applied_on="2026-09-14", **JOB)

    fresh = {"title": "Something Else", "company": "Tailspin",
             "url": "https://www.upwork.com/jobs/~01bbbb2222cccc3333"}
    body = check(client, headers, khuram["id"], fresh, JOB)

    assert [m["index"] for m in body["matches"]] == [1]
    [hit] = body["matches"][0]["applied"]
    assert hit["profile"] == "Khuram"
    assert hit["profile_id"] == khuram["id"]
    assert hit["this_profile"] is True
    assert hit["applied_on"] == "2026-09-14"
    assert hit["source"] == "own"
    assert hit["company"] == "Northwind"
    assert hit["title"] == "RAG Engineer"
    assert hit["url"]


def test_check_matches_by_fingerprint_not_by_the_text_typed(client, manager):
    """The same posting through another link is the same posting."""
    headers, _bd, khuram, _zahid = one_bd_two_profiles(client, manager)
    log(client, headers, khuram["id"], **JOB)

    other_link = {"title": "Senior RAG Eng", "company": "Northwind",
                  "url": "https://www.upwork.com/ab/proposals/~017acdef99120abc44"}
    body = check(client, headers, khuram["id"], other_link)
    assert [m["index"] for m in body["matches"]] == [0]
    # And filing agrees with the check.
    assert log(client, headers, khuram["id"], **other_link)["duplicate"] == 1


def test_check_writes_nothing(client, manager):
    headers, _bd, khuram, zahid = one_bd_two_profiles(client, manager)
    body = check(client, headers, khuram["id"], JOB)
    assert body == {"matches": []}
    assert own(client, headers, khuram["id"]) == []
    assert client.get("/jobs", headers=manager).json() == []
    assert client.get(f"/profiles/{zahid['id']}/others", headers=headers).json() == []


def test_check_looks_across_every_profile_the_bd_holds(client, manager):
    headers, _bd, khuram, zahid = one_bd_two_profiles(client, manager)
    log(client, headers, khuram["id"], **JOB)

    body = check(client, headers, zahid["id"], JOB)

    [hit] = body["matches"][0]["applied"]
    assert hit["profile"] == "Khuram"
    assert hit["this_profile"] is False
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", hit["applied_on"])


def test_check_ignores_other_bds_profiles(client, manager):
    headers, _bd, khuram, _zahid = one_bd_two_profiles(client, manager)
    bilal = make_bd(client, manager, "Bilal", "bilal@mbs.co")
    his = sign_in(client, "bilal@mbs.co", "secret")
    hamza = make_profile(client, manager, "Hamza", bilal["id"])
    log(client, headers, khuram["id"], **JOB)

    assert check(client, his, hamza["id"], JOB) == {"matches": []}


def test_check_lists_both_an_own_and_an_others_application(client, manager):
    headers, _bd, khuram, zahid = one_bd_two_profiles(client, manager)
    log(client, headers, khuram["id"], **JOB)
    handed = client.get(f"/profiles/{zahid['id']}/others", headers=headers).json()
    client.post(f"/assignments/{handed[0]['assignment_id']}", headers=headers,
                json={"status": "applied"})

    applied = check(client, headers, zahid["id"], JOB)["matches"][0]["applied"]

    assert [(a["profile"], a["source"], a["this_profile"]) for a in applied] == [
        ("Khuram", "own", False), ("Zahid", "others", True)]


# --------------------------------------------------------------------------- #
# Filing it anyway
# --------------------------------------------------------------------------- #

def test_filing_the_same_job_again_is_a_duplicate(client, manager):
    headers, _bd, khuram, _zahid = one_bd_two_profiles(client, manager)
    log(client, headers, khuram["id"], **JOB)

    tally = log(client, headers, khuram["id"], **JOB)

    assert tally == {"added": 0, "known": 0, "duplicate": 1, "reapplied": 0,
                     "unusable": 0}
    assert len(own(client, headers, khuram["id"])) == 1


def test_reapply_files_a_second_application(client, manager):
    headers, _bd, khuram, _zahid = one_bd_two_profiles(client, manager)
    log(client, headers, khuram["id"], **JOB)

    tally = log(client, headers, khuram["id"], reapply=True, **JOB)

    assert tally["reapplied"] == 1 and tally["duplicate"] == 0
    rows = own(client, headers, khuram["id"])
    assert len(rows) == 2
    assert {r["title"] for r in rows} == {"RAG Engineer"}
    # Still one posting in the pool.
    assert len(client.get("/jobs", headers=manager).json()) == 1


def test_reapply_on_a_job_never_applied_for_is_just_a_find(client, manager):
    headers, _bd, khuram, _zahid = one_bd_two_profiles(client, manager)
    tally = log(client, headers, khuram["id"], reapply=True, **JOB)
    assert tally["added"] == 1 and tally["reapplied"] == 0


# --------------------------------------------------------------------------- #
# Why it was skipped
# --------------------------------------------------------------------------- #

def handed_to_zahid(client, manager):
    headers, _bd, khuram, zahid = one_bd_two_profiles(client, manager)
    log(client, headers, khuram["id"], **JOB)
    log(client, headers, khuram["id"], title="NLP Engineer", company="Corvid",
        url="https://www.upwork.com/jobs/~01bbbb2222cccc3333")
    handed = client.get(f"/profiles/{zahid['id']}/others", headers=headers).json()
    return headers, zahid, handed


def skipped(client, headers, profile):
    return client.get(f"/profiles/{profile['id']}/others", headers=headers,
                      params={"status": "skipped"}).json()


def test_a_skip_keeps_its_reason(client, manager):
    headers, zahid, handed = handed_to_zahid(client, manager)
    row = handed[0]["assignment_id"]

    reply = client.post(f"/assignments/{row}", headers=headers,
                        json={"status": "skipped", "reason": "Budget too low"})

    assert reply.status_code == 200, reply.text
    assert reply.json()["skip_reason"] == "Budget too low"
    [listed] = skipped(client, headers, zahid)
    assert listed["assignment_id"] == row
    assert listed["skip_reason"] == "Budget too low"


def test_moving_back_to_pending_clears_the_reason(client, manager):
    headers, zahid, handed = handed_to_zahid(client, manager)
    row = handed[0]["assignment_id"]
    client.post(f"/assignments/{row}", headers=headers,
                json={"status": "skipped", "reason": "Budget too low"})

    reply = client.post(f"/assignments/{row}", headers=headers,
                        json={"status": "pending"})

    assert reply.json()["skip_reason"] == ""
    pending = client.get(f"/profiles/{zahid['id']}/others", headers=headers,
                         params={"status": "pending"}).json()
    assert {p["skip_reason"] for p in pending} == {""}


def test_a_bulk_skip_puts_the_reason_on_every_row(client, manager):
    headers, zahid, handed = handed_to_zahid(client, manager)
    ids = [h["assignment_id"] for h in handed]

    reply = client.post("/assignments/bulk", headers=headers, json={
        "ids": ids, "status": "skipped", "reason": "Wrong stack"})

    assert reply.status_code == 200, reply.text
    rows = skipped(client, headers, zahid)
    assert sorted(r["assignment_id"] for r in rows) == sorted(ids)
    assert {r["skip_reason"] for r in rows} == {"Wrong stack"}


def test_a_bulk_skip_can_change_the_reason_on_rows_already_skipped(client,
                                                                   manager):
    headers, zahid, handed = handed_to_zahid(client, manager)
    ids = [h["assignment_id"] for h in handed]
    client.post("/assignments/bulk", headers=headers,
                json={"ids": ids, "status": "skipped", "reason": "Wrong stack"})

    client.post("/assignments/bulk", headers=headers,
                json={"ids": ids, "status": "skipped", "reason": "Client ghosted"})

    assert {r["skip_reason"] for r in skipped(client, headers, zahid)} == {
        "Client ghosted"}


# --------------------------------------------------------------------------- #
# A manager editing somebody
# --------------------------------------------------------------------------- #

def test_a_manager_can_change_somebodys_email(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    reply = client.patch(f"/users/{bd['id']}", headers=manager,
                         json={"email": "Ayesha.Raza@mbs.co"})
    assert reply.status_code == 200, reply.text

    sign_in(client, "ayesha.raza@mbs.co", "secret")
    old = client.post("/auth/login",
                      json={"email": "ayesha@mbs.co", "password": "secret"})
    assert old.status_code == 401


def test_an_email_somebody_else_uses_is_refused(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    make_bd(client, manager, "Bilal", "bilal@mbs.co")
    reply = client.patch(f"/users/{bd['id']}", headers=manager,
                         json={"email": "bilal@mbs.co"})
    assert reply.status_code == 409


def test_a_manager_can_change_somebodys_role(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    reply = client.patch(f"/users/{bd['id']}", headers=manager,
                         json={"role": "manager"})
    assert reply.status_code == 200, reply.text

    promoted = sign_in(client, "ayesha@mbs.co", "secret")
    assert client.get("/overview", headers=promoted).status_code == 200


def test_a_role_that_does_not_exist_is_refused(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    reply = client.patch(f"/users/{bd['id']}", headers=manager,
                         json={"role": "owner"})
    assert reply.status_code == 400


def test_a_manager_cannot_change_their_own_role(client, manager):
    me = client.get("/auth/me", headers=manager).json()
    reply = client.patch(f"/users/{me['id']}", headers=manager,
                         json={"role": "bd"})
    assert reply.status_code == 400
    assert client.get("/auth/me", headers=manager).json()["role"] == "manager"
