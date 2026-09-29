"""The skipped report: how much each BD turned down, and why."""
from conftest import sign_in

from app.dispatch import OTHER, reason_category
from helpers import log, make_bd, make_profile


def test_a_reason_is_filed_under_its_suggestion_whatever_the_case():
    assert reason_category("  budget TOO low ") == "Budget too low"
    assert reason_category("Client wants onsite") == OTHER
    assert reason_category("") == OTHER


def test_skips_are_counted_per_bd_and_per_reason(client, manager):
    finder = make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    skipper = make_bd(client, manager, "Zahid", "zahid@mbs.co")
    mine = sign_in(client, "ayesha@mbs.co", "secret")
    theirs = sign_in(client, "zahid@mbs.co", "secret")
    found = make_profile(client, manager, "Khuram", finder["id"])
    other = make_profile(client, manager, "Zain", skipper["id"])
    for n in range(3):
        log(client, mine, found["id"], title=f"Job {n}", company=f"Co {n}",
            url=f"https://example.com/{n}")

    pending = client.get(f"/profiles/{other['id']}/others", headers=theirs).json()
    assert len(pending) == 3
    for row, reason in zip(pending, ["budget too low", "Onsite only", ""]):
        client.post(f"/assignments/{row['assignment_id']}", headers=theirs,
                    json={"status": "skipped", "reason": reason})

    report = client.get("/reports/skipped", headers=manager).json()
    zahid = next(p for p in report["people"] if p["name"] == "Zahid")
    assert zahid["skipped"] == 3 and zahid["given"] == 3 and zahid["rate"] == 1
    assert zahid["by_reason"]["Budget too low"] == 1
    assert zahid["by_reason"][OTHER] == 2
    assert report["totals"]["skipped"] == 3
    assert {r["reason"] for r in report["other_reasons"]} == {"Onsite only",
                                                              "(no reason given)"}
    # The overview and the report agree about what skipped means.
    people = client.get("/overview", headers=manager).json()["people"]
    assert next(p for p in people if p["name"] == "Zahid")["skipped"] == 3


def test_only_a_manager_reads_the_report(client, manager):
    make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    bd = sign_in(client, "ayesha@mbs.co", "secret")
    assert client.get("/reports/skipped", headers=bd).status_code == 403
