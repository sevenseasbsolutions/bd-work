"""The whole app, through its own API.

One manager, two BDs, three profiles, and the five words the product is made
of: own jobs, others' jobs, skipped, applied, all jobs.
"""
from conftest import sign_in
from helpers import log, make_bd, make_profile


# --------------------------------------------------------------------------- #
# Signing in
# --------------------------------------------------------------------------- #

def test_the_first_boot_mints_a_manager(client):
    reply = client.post("/auth/login",
                        json={"email": "manager@mbs.co", "password": "manager"})
    assert reply.status_code == 200
    assert reply.json()["user"]["role"] == "manager"


def test_a_wrong_password_says_nothing_about_the_address(client):
    known = client.post("/auth/login",
                        json={"email": "manager@mbs.co", "password": "nope"})
    unknown = client.post("/auth/login",
                          json={"email": "ghost@mbs.co", "password": "nope"})
    assert known.status_code == unknown.status_code == 401
    assert known.json()["detail"] == unknown.json()["detail"]


def test_no_token_gets_nowhere(client):
    assert client.get("/profiles").status_code == 401


# --------------------------------------------------------------------------- #
# People and profiles — the manager's half
# --------------------------------------------------------------------------- #

def test_manager_adds_a_bd_and_assigns_them_a_profile(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    profile = make_profile(client, manager, "Khuram — AI Engineer", bd["id"],
                           headline="AI Engineer", platform="Upwork")
    assert profile["bd"] == "Ayesha"

    mine = client.get("/profiles", headers=sign_in(client, "ayesha@mbs.co", "secret"))
    assert [p["name"] for p in mine.json()] == ["Khuram — AI Engineer"]


def test_a_bd_cannot_reach_the_manager_screens(client, manager):
    make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    bd = sign_in(client, "ayesha@mbs.co", "secret")
    assert client.get("/overview", headers=bd).status_code == 403
    assert client.get("/users", headers=bd).status_code == 403
    assert client.post("/profiles", headers=bd, json={"name": "X"}).status_code == 403


def test_two_profiles_cannot_share_a_name(client, manager):
    make_profile(client, manager, "Khuram — AI Engineer")
    clash = client.post("/profiles", headers=manager,
                        json={"name": "khuram — ai engineer"})
    assert clash.status_code == 409


def test_deleting_a_bd_frees_their_profiles_rather_than_the_history(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    profile = make_profile(client, manager, "Khuram", bd["id"])
    log(client, sign_in(client, "ayesha@mbs.co", "secret"), profile["id"],
        title="RAG Engineer", company="Northwind", url="https://upwork.com/jobs/~01aaaabbbbcccc11")

    reply = client.delete(f"/users/{bd['id']}", headers=manager)
    assert reply.json()["profiles_unassigned"] == 1

    after = client.get("/overview", headers=manager).json()
    assert after["totals"]["own"] == 1          # the work survived the person
    assert after["totals"]["unassigned"] == 1


def test_a_manager_cannot_switch_themselves_off(client, manager):
    me = client.get("/auth/me", headers=manager).json()
    reply = client.patch(f"/users/{me['id']}", headers=manager, json={"is_active": False})
    assert reply.status_code == 400


# --------------------------------------------------------------------------- #
# The pool: a find becomes everybody else's others' job
# --------------------------------------------------------------------------- #

def test_a_find_lands_on_every_other_profile(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    headers = sign_in(client, "ayesha@mbs.co", "secret")
    finder = make_profile(client, manager, "Khuram", bd["id"])
    one = make_profile(client, manager, "Zahid", bd["id"])
    two = make_profile(client, manager, "Hamza", bd["id"])

    log(client, headers, finder["id"], title="RAG Engineer", company="Northwind",
        url="https://www.upwork.com/jobs/~017acdef99120abc44")

    own = client.get(f"/profiles/{finder['id']}/own", headers=headers).json()
    assert len(own) == 1 and own[0]["title"] == "RAG Engineer"
    # The finder is never handed its own find.
    assert client.get(f"/profiles/{finder['id']}/others", headers=headers).json() == []

    for other in (one, two):
        handed = client.get(f"/profiles/{other['id']}/others", headers=headers).json()
        # "Found by" names the BD who holds the finding profile, not the profile.
        assert [row["found_by"] for row in handed] == ["Ayesha"]


def test_the_same_posting_through_two_links_is_one_job(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    headers = sign_in(client, "ayesha@mbs.co", "secret")
    one = make_profile(client, manager, "Khuram", bd["id"])
    two = make_profile(client, manager, "Zahid", bd["id"])

    added = log(client, headers, one["id"], title="RAG Engineer", company="Northwind",
                url="https://www.upwork.com/jobs/~017acdef99120abc44?ref=feed")
    known = log(client, headers, two["id"], title="Senior RAG Eng", company="Northwind",
                url="https://www.upwork.com/ab/proposals/~017acdef99120abc44")
    assert added["added"] == 1 and known["known"] == 1

    pool = client.get("/jobs", headers=manager).json()
    assert len(pool) == 1 and pool[0]["applications"] == 2


def test_the_same_profile_cannot_apply_twice(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    headers = sign_in(client, "ayesha@mbs.co", "secret")
    profile = make_profile(client, manager, "Khuram", bd["id"])
    url = "https://www.linkedin.com/jobs/view/4123998877"

    assert log(client, headers, profile["id"], title="Dev", url=url)["added"] == 1
    assert log(client, headers, profile["id"], title="Dev", url=url)["duplicate"] == 1
    assert len(client.get(f"/profiles/{profile['id']}/own", headers=headers).json()) == 1


def test_a_row_with_nothing_usable_is_reported_not_saved(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    headers = sign_in(client, "ayesha@mbs.co", "secret")
    profile = make_profile(client, manager, "Khuram", bd["id"])
    tally = log(client, headers, profile["id"], title="", company="", url="")
    assert tally["unusable"] == 1
    assert client.get(f"/profiles/{profile['id']}/own", headers=headers).json() == []


def test_a_paste_of_many_rows_saves_the_good_ones(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    headers = sign_in(client, "ayesha@mbs.co", "secret")
    profile = make_profile(client, manager, "Khuram", bd["id"])
    reply = client.post(f"/profiles/{profile['id']}/own", headers=headers, json={"jobs": [
        {"title": "A", "url": "https://www.linkedin.com/jobs/view/4000000001"},
        {"title": "B", "url": "https://www.linkedin.com/jobs/view/4000000002"},
        {"title": "", "url": ""},
    ]})
    assert reply.json() == {"added": 2, "known": 0, "duplicate": 0,
                            "reapplied": 0, "unusable": 1}


# --------------------------------------------------------------------------- #
# Working an others' job
# --------------------------------------------------------------------------- #

def two_profiles_one_job(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    headers = sign_in(client, "ayesha@mbs.co", "secret")
    finder = make_profile(client, manager, "Khuram", bd["id"])
    other = make_profile(client, manager, "Zahid", bd["id"])
    log(client, headers, finder["id"], title="RAG Engineer", company="Northwind",
        url="https://www.upwork.com/jobs/~017acdef99120abc44")
    handed = client.get(f"/profiles/{other['id']}/others", headers=headers).json()
    return headers, finder, other, handed[0]


def test_applying_for_an_others_job_counts_as_applied_not_as_own(client, manager):
    headers, finder, other, row = two_profiles_one_job(client, manager)
    reply = client.post(f"/assignments/{row['assignment_id']}", headers=headers,
                        json={"status": "applied", "applied_on": "2026-09-16"})
    assert reply.json()["status"] == "applied"

    assert client.get(f"/profiles/{other['id']}/own", headers=headers).json() == []
    done = client.get(f"/profiles/{other['id']}/others?status=applied",
                      headers=headers).json()
    assert len(done) == 1

    counts = {p["name"]: p["counts"]
              for p in client.get("/overview", headers=manager).json()["profiles"]}
    assert counts["Khuram"]["own"] == 1 and counts["Khuram"]["from_others"] == 0
    assert counts["Zahid"]["own"] == 0 and counts["Zahid"]["from_others"] == 1
    assert counts["Zahid"]["applied"] == 1 and counts["Zahid"]["pending"] == 0


def test_skipping_moves_it_out_of_the_way_and_counts_nothing_as_applied(client, manager):
    headers, _finder, other, row = two_profiles_one_job(client, manager)
    client.post(f"/assignments/{row['assignment_id']}", headers=headers,
                json={"status": "skipped"})

    assert client.get(f"/profiles/{other['id']}/others", headers=headers).json() == []
    skipped = client.get(f"/profiles/{other['id']}/others?status=skipped",
                         headers=headers).json()
    assert len(skipped) == 1

    counts = {p["name"]: p["counts"]
              for p in client.get("/overview", headers=manager).json()["profiles"]}
    assert counts["Zahid"]["skipped"] == 1 and counts["Zahid"]["applied"] == 0


def test_undoing_an_apply_takes_the_application_back_off(client, manager):
    headers, _finder, other, row = two_profiles_one_job(client, manager)
    client.post(f"/assignments/{row['assignment_id']}", headers=headers,
                json={"status": "applied"})
    client.post(f"/assignments/{row['assignment_id']}", headers=headers,
                json={"status": "pending"})

    counts = {p["name"]: p["counts"]
              for p in client.get("/overview", headers=manager).json()["profiles"]}
    assert counts["Zahid"]["applied"] == 0 and counts["Zahid"]["pending"] == 1


def test_logging_a_find_closes_the_same_job_off_the_waiting_list(client, manager):
    """A BD who applied without pressing the button still gets a clean list."""
    headers, _finder, other, row = two_profiles_one_job(client, manager)
    log(client, headers, other["id"], title="RAG Engineer", company="Northwind",
        url="https://www.upwork.com/jobs/~017acdef99120abc44")
    assert client.get(f"/profiles/{other['id']}/others", headers=headers).json() == []
    counts = {p["name"]: p["counts"]
              for p in client.get("/overview", headers=manager).json()["profiles"]}
    assert counts["Zahid"]["own"] == 1 and counts["Zahid"]["pending"] == 0


# --------------------------------------------------------------------------- #
# All jobs
# --------------------------------------------------------------------------- #

def test_all_jobs_says_where_this_profile_stands_on_every_row(client, manager):
    headers, finder, other, row = two_profiles_one_job(client, manager)
    log(client, headers, finder["id"], title="NLP Engineer", company="Corvid",
        url="https://www.upwork.com/jobs/~01bbbb2222cccc3333")

    mine = client.get(f"/profiles/{finder['id']}/all", headers=headers).json()
    assert {job["standing"] for job in mine} == {"own"}

    theirs = client.get(f"/profiles/{other['id']}/all", headers=headers).json()
    assert {job["standing"] for job in theirs} == {"pending"}

    client.post(f"/assignments/{row['assignment_id']}", headers=headers,
                json={"status": "skipped"})
    theirs = client.get(f"/profiles/{other['id']}/all", headers=headers).json()
    standings = {job["title"]: job["standing"] for job in theirs}
    assert standings["RAG Engineer"] == "skipped"
    assert standings["NLP Engineer"] == "pending"


def test_all_jobs_names_who_found_it_and_who_has_applied(client, manager):
    headers, _finder, _other, row = two_profiles_one_job(client, manager)
    client.post(f"/assignments/{row['assignment_id']}", headers=headers,
                json={"status": "applied"})
    pool = client.get("/jobs", headers=manager).json()
    assert pool[0]["found_by"] == "Ayesha"     # the BD, not the profile
    assert sorted(pool[0]["applied_by"]) == ["Khuram", "Zahid"]


# --------------------------------------------------------------------------- #
# Who can see what
# --------------------------------------------------------------------------- #

def test_a_bd_cannot_open_somebody_elses_profile(client, manager):
    one = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    make_bd(client, manager, "Bilal", "bilal@mbs.co")
    hers = make_profile(client, manager, "Khuram", one["id"])
    his = sign_in(client, "bilal@mbs.co", "secret")

    assert client.get(f"/profiles/{hers['id']}/own", headers=his).status_code == 403
    assert client.get(f"/profiles/{hers['id']}/others", headers=his).status_code == 403
    assert client.get(f"/profiles/{hers['id']}/all", headers=his).status_code == 403


def test_a_manager_can_read_any_profile_but_not_log_its_work(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    profile = make_profile(client, manager, "Khuram", bd["id"])
    assert client.get(f"/profiles/{profile['id']}/all", headers=manager).status_code == 200
    blocked = client.post(f"/profiles/{profile['id']}/own", headers=manager,
                          json={"jobs": [{"title": "X", "company": "Y"}]})
    assert blocked.status_code == 403


# --------------------------------------------------------------------------- #
# Turning a profile on and off
# --------------------------------------------------------------------------- #

def test_a_new_profile_is_handed_the_pool_that_already_exists(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    headers = sign_in(client, "ayesha@mbs.co", "secret")
    finder = make_profile(client, manager, "Khuram", bd["id"])
    log(client, headers, finder["id"], title="RAG Engineer", company="Northwind",
        url="https://www.upwork.com/jobs/~017acdef99120abc44")
    log(client, headers, finder["id"], title="NLP Engineer", company="Corvid",
        url="https://www.upwork.com/jobs/~01bbbb2222cccc3333")

    latecomer = make_profile(client, manager, "Zahid", bd["id"])
    assert latecomer["handed_over"] == 2
    assert len(client.get(f"/profiles/{latecomer['id']}/others",
                          headers=headers).json()) == 2


def test_switching_a_profile_off_gives_back_what_it_never_worked(client, manager):
    headers, _finder, other, _row = two_profiles_one_job(client, manager)
    client.patch(f"/profiles/{other['id']}", headers=manager, json={"is_active": False})
    counts = {p["name"]: p["counts"]
              for p in client.get("/overview", headers=manager).json()["profiles"]}
    assert counts["Zahid"]["pending"] == 0

    back = client.patch(f"/profiles/{other['id']}", headers=manager,
                        json={"is_active": True})
    assert back.json()["handed_over"] == 1


def test_an_inactive_profile_is_not_handed_new_finds(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    headers = sign_in(client, "ayesha@mbs.co", "secret")
    finder = make_profile(client, manager, "Khuram", bd["id"])
    asleep = make_profile(client, manager, "Zahid", bd["id"])
    client.patch(f"/profiles/{asleep['id']}", headers=manager, json={"is_active": False})

    log(client, headers, finder["id"], title="RAG Engineer", company="Northwind",
        url="https://www.upwork.com/jobs/~017acdef99120abc44")
    counts = {p["name"]: p["counts"]
              for p in client.get("/overview", headers=manager).json()["profiles"]}
    assert counts["Zahid"]["given"] == 0


def test_deleting_a_profile_leaves_the_pool_alone(client, manager):
    headers, finder, other, row = two_profiles_one_job(client, manager)
    client.post(f"/assignments/{row['assignment_id']}", headers=headers,
                json={"status": "applied"})
    client.delete(f"/profiles/{finder['id']}", headers=manager)

    pool = client.get("/jobs", headers=manager).json()
    assert len(pool) == 1
    assert pool[0]["applied_by"] == ["Zahid"]   # the deleted identity is gone
    assert pool[0]["found_by"] == ""            # and nobody is credited with it


# --------------------------------------------------------------------------- #
# The manager's numbers
# --------------------------------------------------------------------------- #

def test_the_overview_adds_a_bds_profiles_together(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    headers = sign_in(client, "ayesha@mbs.co", "secret")
    one = make_profile(client, manager, "Khuram", bd["id"])
    two = make_profile(client, manager, "Zahid", bd["id"])
    log(client, headers, one["id"], title="A",
        url="https://www.linkedin.com/jobs/view/4000000001")
    log(client, headers, two["id"], title="B",
        url="https://www.linkedin.com/jobs/view/4000000002")

    seat = client.get("/overview", headers=manager).json()["people"][0]
    assert seat["name"] == "Ayesha"
    assert sorted(seat["profiles"]) == ["Khuram", "Zahid"]
    assert seat["own"] == 2 and seat["pending"] == 2   # each got the other's find


# --------------------------------------------------------------------------- #
# Undoing a find
# --------------------------------------------------------------------------- #

def test_removing_a_find_nobody_else_touched_withdraws_the_posting(client, manager):
    """A typo dispatched to eight profiles has to be withdrawable."""
    headers, finder, other, _row = two_profiles_one_job(client, manager)
    entry = client.get(f"/profiles/{finder['id']}/own", headers=headers).json()[0]

    reply = client.delete(f"/profiles/{finder['id']}/own/{entry['application_id']}",
                          headers=headers)
    assert reply.json()["job_withdrawn"] is True
    assert client.get("/jobs", headers=manager).json() == []
    assert client.get(f"/profiles/{other['id']}/others", headers=headers).json() == []


def test_removing_a_find_a_colleague_applied_for_leaves_the_posting(client, manager):
    headers, finder, other, row = two_profiles_one_job(client, manager)
    client.post(f"/assignments/{row['assignment_id']}", headers=headers,
                json={"status": "applied"})
    entry = client.get(f"/profiles/{finder['id']}/own", headers=headers).json()[0]

    reply = client.delete(f"/profiles/{finder['id']}/own/{entry['application_id']}",
                          headers=headers)
    assert reply.json()["job_withdrawn"] is False

    pool = client.get("/jobs", headers=manager).json()
    assert len(pool) == 1 and pool[0]["applied_by"] == ["Zahid"]


# --------------------------------------------------------------------------- #
# The entry line: client, title, link, platform, email, date
# --------------------------------------------------------------------------- #

def test_an_entry_keeps_the_address_and_the_date_it_went_out_from(client, manager):
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    headers = sign_in(client, "ayesha@mbs.co", "secret")
    profile = make_profile(client, manager, "Khuram", bd["id"])
    log(client, headers, profile["id"], company="Northwind Labs",
        title="Senior RAG Engineer", url="https://www.upwork.com/jobs/~017acdef99120abc44",
        platform="Upwork", email="khuram.apply@mbs.co", applied_on="2026-09-16")

    entry = client.get(f"/profiles/{profile['id']}/own", headers=headers).json()[0]
    assert entry["email"] == "khuram.apply@mbs.co"
    assert entry["applied_on"] == "2026-09-16"

    # And it comes back on the all-jobs row, which is what the copy button copies.
    row = client.get(f"/profiles/{profile['id']}/all", headers=headers).json()[0]
    assert row["my_email"] == "khuram.apply@mbs.co" and row["my_date"] == "2026-09-16"


def test_a_colleagues_entry_line_is_not_on_your_all_jobs_row(client, manager):
    """my_email is this profile's, never whoever else applied."""
    bd = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    headers = sign_in(client, "ayesha@mbs.co", "secret")
    finder = make_profile(client, manager, "Khuram", bd["id"])
    other = make_profile(client, manager, "Zahid", bd["id"])
    log(client, headers, finder["id"], company="Northwind", title="RAG Engineer",
        url="https://www.upwork.com/jobs/~017acdef99120abc44",
        email="khuram.apply@mbs.co", applied_on="2026-09-16")

    row = client.get(f"/profiles/{other['id']}/all", headers=headers).json()[0]
    assert row["standing"] == "pending"
    assert row["my_email"] == "" and row["my_date"] == ""
