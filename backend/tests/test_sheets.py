"""The Google Sheet mirror: a tab per BD in one file, the manager in another.

Google is not here, so the spreadsheets are. `Paper` below keeps its tabs in a
dict — not a mock of the Sheets wire protocol but the same six methods
`GoogleWorkbook` has, doing what a spreadsheet does with them. Every assertion
is then about MBS: which rows it decided to send, onto whose tab, into which
file, and whether the tab still matches the database after somebody pressed
Undo.
"""
from __future__ import annotations

import pytest
from helpers import log, make_bd, make_profile
from test_imports import job_rows, sheet, upload
from conftest import sign_in

from app import sheets
from app.db import SessionLocal

TEAM = "1TheTeamFile"
BOSS = "1TheManagerFile"


class Paper:
    """A spreadsheet made of lists. The six methods sheets.py calls."""

    def __init__(self, existing: list[str] | None = None) -> None:
        self.pages: dict[str, list[list]] = {}
        self.ids: dict[str, int] = {}
        self._next = 1
        for name in existing or []:
            self._make(name)
        self.appends = 0
        self.clears = 0

    def _make(self, name):
        self.pages[name] = []
        self.ids[name] = self._next
        self._next += 1

    # -- the GoogleWorkbook interface --------------------------------------- #
    def tabs(self) -> dict[str, int]:
        return dict(self.ids)

    def add_tabs(self, names):
        for name in names:
            if name not in self.pages:
                self._make(name)

    def rename_tab(self, tab_id, name):
        old = next(n for n, i in self.ids.items() if i == tab_id)
        self.pages[name] = self.pages.pop(old)
        self.ids[name] = self.ids.pop(old)

    def delete_tabs(self, tab_ids):
        for one in tab_ids:
            name = next((n for n, i in self.ids.items() if i == one), None)
            if name:
                del self.pages[name]
                del self.ids[name]

    def clear(self, tab):
        self.clears += 1
        self.pages[tab] = []

    def append(self, tab, rows):
        self.appends += 1
        self.pages[tab].extend(rows)

    # -- what the tests ask it ---------------------------------------------- #
    def body(self, tab) -> list[list]:
        return self.pages[tab][1:]

    def column(self, tab, heading) -> list:
        at = self.pages[tab][0].index(heading)
        return [row[at] for row in self.body(tab)]


@pytest.fixture()
def on(client, manager, monkeypatch):
    """The mirror switched on and pointed at both files, as a manager would."""
    monkeypatch.setenv("MBS_GOOGLE_CREDENTIALS", "{}")
    assert client.patch("/settings", headers=manager,
                        json={"sheet_sync": True}).status_code == 200
    assert client.put("/sheets", headers=manager, json={
        "team_sheet": TEAM, "manager_sheet": BOSS}).status_code == 200
    return manager


def target_for(bd) -> sheets.Target:
    """One BD, as the tab their work goes on."""
    return sheets.Target(f"bd:{bd['id']}", sheets.tab_name(bd["name"]),
                         bd["id"], bd["name"])


def pass_over(paper, bd, **kw) -> dict:
    """One pass over one BD's tab, as the timer would run it."""
    with SessionLocal() as db:
        return sheets.sync_bd(db, paper, paper.tabs(), target_for(bd), **kw)


def both_files(monkeypatch, team, boss):
    monkeypatch.setattr(sheets, "open_book",
                        lambda where: team if where == TEAM else boss)


def whole_pass(monkeypatch, team, boss, derived=True, rebuild=False):
    """A pass over both files, through the real `one_pass`."""
    both_files(monkeypatch, team, boss)
    return sheets.one_pass(derived=derived, rebuild=rebuild)


def crew(client, manager):
    """Ayesha and Bilal, a profile each."""
    ayesha = make_bd(client, manager, "Ayesha Raza", "ayesha@mbs.co")
    bilal = make_bd(client, manager, "Bilal Khan", "bilal@mbs.co")
    khuram = make_profile(client, manager, "Khuram — AI Engineer", ayesha["id"])
    hamza = make_profile(client, manager, "Hamza — Full Stack", bilal["id"])
    return (sign_in(client, "ayesha@mbs.co", "secret"), ayesha, khuram,
            sign_in(client, "bilal@mbs.co", "secret"), bilal, hamza)


# --------------------------------------------------------------------------- #
# A tab per BD, by their name
# --------------------------------------------------------------------------- #

def test_every_bd_gets_a_tab_named_after_them(client, manager, on, monkeypatch):
    crew(client, manager)
    team, boss = Paper(), Paper()

    whole_pass(monkeypatch, team, boss)

    assert "Ayesha Raza" in team.tabs()
    assert "Bilal Khan" in team.tabs()
    # Names, not profiles.
    assert "Khuram — AI Engineer" not in team.tabs()


def test_a_tab_carries_only_that_bds_applied_jobs(client, manager, on):
    hers, ayesha, khuram, his, bilal, hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Ayesha Found This", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    log(client, his, hamza["id"], company="Bilal Found This", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000002")

    team = Paper()
    pass_over(team, ayesha)
    pass_over(team, bilal)

    assert team.column("Ayesha Raza", "Company name") == ["Ayesha Found This"]
    assert team.column("Bilal Khan", "Company name") == ["Bilal Found This"]


def test_both_of_one_bds_profiles_land_on_their_one_tab(client, manager, on):
    """The reason the Profile column is there: one person, several identities."""
    hers, ayesha, khuram, _his, _bilal, _hamza = crew(client, manager)
    zahid = make_profile(client, manager, "Zahid — ML Engineer", ayesha["id"])

    log(client, hers, khuram["id"], company="Under Khuram", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    log(client, hers, zahid["id"], company="Under Zahid", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000002")

    team = Paper()
    pass_over(team, ayesha)

    assert team.column("Ayesha Raza", "Company name") == ["Under Khuram",
                                                          "Under Zahid"]
    assert team.column("Ayesha Raza", "Profile") == ["Khuram — AI Engineer",
                                                     "Zahid — ML Engineer"]


def test_the_columns_are_the_attributes_of_an_applied_job(client, manager, on):
    hers, ayesha, khuram, _his, _bilal, _hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001",
        platform="LinkedIn", email="khuram@mbs.co", applied_on="2026-09-14")

    team = Paper()
    pass_over(team, ayesha)

    assert team.pages["Ayesha Raza"][0] == sheets.APPLIED_COLUMNS
    row = dict(zip(sheets.APPLIED_COLUMNS, team.body("Ayesha Raza")[0]))
    assert row["Applied on"] == "2026-09-14"
    assert row["Profile"] == "Khuram — AI Engineer"
    assert row["Company name"] == "Northwind"
    assert row["Job title"] == "Engineer"
    assert row["Job link"] == "https://www.linkedin.com/jobs/view/3912000001"
    assert row["Job platform"] == "LinkedIn"
    assert row["Email"] == "khuram@mbs.co"
    assert row["Own or others"] == "Own job"
    assert row["Found by"] == "Khuram — AI Engineer"


def test_a_name_google_will_not_take_is_made_into_one(client, manager):
    r"""Google refuses : \ / ? * [ ] in a tab name, and caps it at 100."""
    assert sheets.tab_name("Ali / Data [Contract]") == "Ali Data Contract"
    assert sheets.tab_name("x" * 200) == "x" * 99
    assert sheets.tab_name("") == "Unnamed"


# --------------------------------------------------------------------------- #
# Applied, from either side
# --------------------------------------------------------------------------- #

def test_an_others_job_applied_for_lands_on_the_takers_tab(client, manager, on):
    """Applied is applied, wherever the job came from."""
    hers, ayesha, khuram, his, bilal, hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    handed = client.get(f"/profiles/{hamza['id']}/others", headers=his,
                        params={"status": "pending"}).json()
    client.post(f"/assignments/{handed[0]['assignment_id']}", headers=his,
                json={"status": "applied"})

    team = Paper()
    pass_over(team, bilal)

    row = dict(zip(sheets.APPLIED_COLUMNS, team.body("Bilal Khan")[0]))
    assert row["Own or others"] == "Others job"
    assert row["Company name"] == "Northwind"
    assert row["Profile"] == "Hamza — Full Stack"
    # Whose find it was, which the row cannot say for itself.
    assert row["Found by"] == "Khuram — AI Engineer"


def test_a_pending_job_is_not_on_the_tab_until_it_is_applied_for(client, manager,
                                                                 on):
    hers, ayesha, khuram, his, bilal, hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")

    team = Paper()
    pass_over(team, bilal)
    assert team.body("Bilal Khan") == []

    handed = client.get(f"/profiles/{hamza['id']}/others", headers=his,
                        params={"status": "pending"}).json()
    client.post(f"/assignments/{handed[0]['assignment_id']}", headers=his,
                json={"status": "applied"})

    assert pass_over(team, bilal)["appended"] == 1
    assert team.column("Bilal Khan", "Company name") == ["Northwind"]


def test_a_skipped_job_never_reaches_the_tab(client, manager, on):
    hers, ayesha, khuram, his, bilal, hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    handed = client.get(f"/profiles/{hamza['id']}/others", headers=his,
                        params={"status": "pending"}).json()
    client.post(f"/assignments/{handed[0]['assignment_id']}", headers=his,
                json={"status": "skipped"})

    team = Paper()
    pass_over(team, bilal)
    assert team.body("Bilal Khan") == []


def test_undoing_an_application_takes_its_row_back_off(client, manager, on):
    hers, ayesha, khuram, his, bilal, hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    handed = client.get(f"/profiles/{hamza['id']}/others", headers=his,
                        params={"status": "pending"}).json()
    assignment = handed[0]["assignment_id"]
    client.post(f"/assignments/{assignment}", headers=his,
                json={"status": "applied"})

    team = Paper()
    pass_over(team, bilal)
    assert len(team.body("Bilal Khan")) == 1

    client.post(f"/assignments/{assignment}", headers=his,
                json={"status": "pending"})
    result = pass_over(team, bilal)

    assert result["rebuilt"] is True
    assert team.body("Bilal Khan") == []
    assert team.pages["Bilal Khan"][0] == sheets.APPLIED_COLUMNS


# --------------------------------------------------------------------------- #
# Appending, and only what is new
# --------------------------------------------------------------------------- #

def test_the_second_pass_appends_only_what_is_new(client, manager, on):
    hers, ayesha, khuram, _his, _bilal, _hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    team = Paper()
    pass_over(team, ayesha)

    log(client, hers, khuram["id"], company="Tailspin", title="Analyst",
        url="https://www.linkedin.com/jobs/view/3912000002")
    result = pass_over(team, ayesha)

    assert result["appended"] == 1 and result["rebuilt"] is False
    assert team.column("Ayesha Raza", "Company name") == ["Northwind", "Tailspin"]


def test_a_pass_with_nothing_new_writes_no_rows(client, manager, on):
    hers, ayesha, khuram, _his, _bilal, _hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    team = Paper()
    pass_over(team, ayesha)
    before = team.appends

    result = pass_over(team, ayesha)

    assert result["appended"] == 0 and result["rebuilt"] is False
    assert team.appends == before          # not one wasted call to Google


def test_two_bds_keep_their_own_watermarks(client, manager, on):
    hers, ayesha, khuram, his, bilal, hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Hers One", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    team = Paper()
    pass_over(team, ayesha)
    pass_over(team, bilal)

    log(client, his, hamza["id"], company="His One", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000002")

    assert pass_over(team, bilal)["appended"] == 1
    assert pass_over(team, ayesha)["appended"] == 0
    assert team.column("Ayesha Raza", "Company name") == ["Hers One"]
    assert team.column("Bilal Khan", "Company name") == ["His One"]


def test_a_find_that_reuses_a_freed_id_is_still_noticed(client, manager, on):
    """SQLite hands back the highest rowid it has just freed."""
    hers, ayesha, khuram, _his, _bilal, _hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    team = Paper()
    pass_over(team, ayesha)

    own = client.get(f"/profiles/{khuram['id']}/own", headers=hers).json()
    client.delete(f"/profiles/{khuram['id']}/own/{own[0]['application_id']}",
                  headers=hers)
    log(client, hers, khuram["id"], company="Tailspin", title="Analyst",
        url="https://www.linkedin.com/jobs/view/3912000002")

    result = pass_over(team, ayesha)

    assert result["rebuilt"] is True
    assert team.column("Ayesha Raza", "Company name") == ["Tailspin"]


def test_handing_a_profile_over_moves_its_history_to_the_new_tab(client, manager,
                                                                 on, monkeypatch):
    """A profile keeps its history; whose tab it shows on is whoever holds it."""
    hers, ayesha, khuram, _his, bilal, _hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    team, boss = Paper(), Paper()
    whole_pass(monkeypatch, team, boss)
    assert team.column("Ayesha Raza", "Company name") == ["Northwind"]

    client.patch(f"/profiles/{khuram['id']}", headers=manager,
                 json={"user_id": bilal["id"]})
    whole_pass(monkeypatch, team, boss)

    assert team.body("Ayesha Raza") == []
    assert team.column("Bilal Khan", "Company name") == ["Northwind"]


# --------------------------------------------------------------------------- #
# Somebody hired this afternoon
# --------------------------------------------------------------------------- #

def test_a_new_bd_gets_a_tab_on_the_next_pass(client, manager, on, monkeypatch):
    """Nobody configures anything: the tab list is the BD list."""
    crew(client, manager)
    team, boss = Paper(), Paper()
    whole_pass(monkeypatch, team, boss)
    assert "Sana Iqbal" not in team.tabs()

    sana = make_bd(client, manager, "Sana Iqbal", "sana@mbs.co")
    noor = make_profile(client, manager, "Noor — Frontend", sana["id"])
    whole_pass(monkeypatch, team, boss)

    assert "Sana Iqbal" in team.tabs()
    assert team.pages["Sana Iqbal"][0] == sheets.APPLIED_COLUMNS

    hers = sign_in(client, "sana@mbs.co", "secret")
    log(client, hers, noor["id"], company="Sana Found This", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912009999")
    whole_pass(monkeypatch, team, boss)

    assert team.column("Sana Iqbal", "Company name") == ["Sana Found This"]


def test_a_bd_with_no_profile_yet_still_gets_a_tab(client, manager, on,
                                                   monkeypatch):
    make_bd(client, manager, "Adnan", "adnan@mbs.co")
    team, boss = Paper(), Paper()
    whole_pass(monkeypatch, team, boss)

    assert team.pages["Adnan"] == [sheets.APPLIED_COLUMNS]


def test_a_manager_who_holds_a_profile_is_not_dropped(client, manager, on,
                                                      monkeypatch):
    """Doing the work is what earns a tab, not the role on the account."""
    mine = make_profile(client, manager, "Manager — Side Project", 1)
    log(client, manager, mine["id"], company="Managers Own", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000077")

    team, boss = Paper(), Paper()
    whole_pass(monkeypatch, team, boss)

    assert "Manager" in team.tabs()
    assert team.column("Manager", "Company name") == ["Managers Own"]


def test_renaming_somebody_renames_their_tab_and_keeps_the_rows(client, manager,
                                                                on, monkeypatch):
    """A second tab with the same rows on it would be a record nobody can read."""
    hers, ayesha, khuram, _his, _bilal, _hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    team, boss = Paper(), Paper()
    whole_pass(monkeypatch, team, boss)
    assert team.column("Ayesha Raza", "Company name") == ["Northwind"]

    client.patch(f"/users/{ayesha['id']}", headers=manager,
                 json={"name": "Ayesha R Khan"})
    whole_pass(monkeypatch, team, boss)

    assert "Ayesha Raza" not in team.tabs()
    assert team.column("Ayesha R Khan", "Company name") == ["Northwind"]


# --------------------------------------------------------------------------- #
# The manager's own file
# --------------------------------------------------------------------------- #

def test_the_manager_file_is_the_manager_screens(client, manager, on, monkeypatch):
    hers, ayesha, khuram, his, bilal, hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    handed = client.get(f"/profiles/{hamza['id']}/others", headers=his,
                        params={"status": "pending"}).json()
    client.post(f"/assignments/{handed[0]['assignment_id']}", headers=his,
                json={"status": "applied"})

    team, boss = Paper(), Paper()
    whole_pass(monkeypatch, team, boss)

    screen = client.get("/overview", headers=manager).json()
    summary = {r[0]: r[1] for r in boss.pages[sheets.OVERVIEW_TAB] if r[0]}
    assert summary["Applied in all"] == screen["totals"]["applied"] == 2
    assert summary["Own jobs found"] == screen["totals"]["own"] == 1

    assert boss.column(sheets.BD_TAB, "BD") == ["Ayesha Raza", "Bilal Khan"]
    assert sorted(boss.column(sheets.PROFILES_TAB, "Profile")) == [
        "Hamza — Full Stack", "Khuram — AI Engineer"]
    assert boss.column(sheets.POOL_TAB, "Company name") == ["Northwind"]


def test_the_manager_tabs_are_not_in_the_team_file(client, manager, on,
                                                   monkeypatch):
    """The whole point of two files: a BD opening theirs sees names, not totals."""
    crew(client, manager)
    team, boss = Paper(), Paper()
    whole_pass(monkeypatch, team, boss)

    for tab in sheets.MANAGER_TABS:
        assert tab not in team.tabs()
        assert tab in boss.tabs()
    assert "Ayesha Raza" not in boss.tabs()


def test_the_manager_file_is_rewritten_not_grown(client, manager, on, monkeypatch):
    hers, ayesha, khuram, _his, _bilal, _hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    team, boss = Paper(), Paper()
    whole_pass(monkeypatch, team, boss)
    first = len(boss.pages[sheets.POOL_TAB])

    log(client, hers, khuram["id"], company="Tailspin", title="Analyst",
        url="https://www.linkedin.com/jobs/view/3912000002")
    whole_pass(monkeypatch, team, boss)

    assert first == 2
    assert len(boss.pages[sheets.POOL_TAB]) == 3


def test_the_manager_file_is_skipped_when_derived_is_off(client, manager, on,
                                                         monkeypatch):
    crew(client, manager)
    team, boss = Paper(), Paper()
    whole_pass(monkeypatch, team, boss, derived=False)
    assert boss.tabs() == {}
    assert "Ayesha Raza" in team.tabs()


def test_one_file_alone_is_enough(client, manager, monkeypatch):
    """A team that wants the BD tabs and no manager file still mirrors."""
    monkeypatch.setenv("MBS_GOOGLE_CREDENTIALS", "{}")
    client.patch("/settings", headers=manager, json={"sheet_sync": True})
    client.put("/sheets", headers=manager,
               json={"team_sheet": TEAM, "manager_sheet": ""})
    hers, ayesha, khuram, _his, _bilal, _hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")

    team, boss = Paper(), Paper()
    whole_pass(monkeypatch, team, boss)

    assert team.column("Ayesha Raza", "Company name") == ["Northwind"]
    assert boss.tabs() == {}


def test_the_two_files_may_not_be_the_same_spreadsheet(client, manager,
                                                       monkeypatch):
    """They would fight: one rewrites tabs the other appends to."""
    monkeypatch.setenv("MBS_GOOGLE_CREDENTIALS", "{}")
    clash = client.put("/sheets", headers=manager,
                       json={"team_sheet": TEAM, "manager_sheet": TEAM})
    assert clash.status_code == 409
    assert "two different spreadsheets" in clash.json()["detail"]


# --------------------------------------------------------------------------- #
# An uploaded sheet is still the manager's to let through
# --------------------------------------------------------------------------- #

def test_imports_are_left_out_until_a_manager_says_otherwise(client, manager, on):
    hers, ayesha, khuram, _his, _bilal, _hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Typed By Hand", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    upload(client, hers, khuram["id"], sheet(job_rows(6, start=50)))

    team = Paper()
    pass_over(team, ayesha)
    assert team.column("Ayesha Raza", "Company name") == ["Typed By Hand"]

    client.patch("/settings", headers=manager, json={"sheet_sync_imports": True})
    pass_over(team, ayesha)
    assert len(team.body("Ayesha Raza")) == 7


# --------------------------------------------------------------------------- #
# Tabs that are not ours, or not there
# --------------------------------------------------------------------------- #

def test_a_tab_made_underneath_us_is_not_an_error(client, manager, on):
    """Another writer can create the tab between the read and the add."""
    hers, ayesha, khuram, _his, _bilal, _hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")

    class Racing(Paper):
        def add_tabs(self, names):
            for name in names:
                if name in self.pages:
                    raise RuntimeError(
                        f'Invalid requests[0].addSheet: A sheet with the name '
                        f'"{name}" already exists. Please enter another name.')
                self._make(name)

    team = Racing()
    team._make("Ayesha Raza")                  # somebody else got there first
    result = pass_over(team, ayesha)

    assert result["rebuilt"] is True
    assert team.column("Ayesha Raza", "Company name") == ["Northwind"]


def test_a_failure_that_is_not_a_clash_still_raises(client, manager, on):
    """Only the one collision is swallowed; a real refusal must surface."""
    _hers, ayesha, _k, _his, _bilal, _hamza = crew(client, manager)

    class Refusing(Paper):
        def add_tabs(self, names):
            raise RuntimeError("caller does not have permission")

    with pytest.raises(RuntimeError, match="permission"):
        pass_over(Refusing(), ayesha)


def test_a_tab_of_ours_that_was_deleted_is_written_again(client, manager, on):
    """Somebody tidying up the spreadsheet must not leave a headless tab."""
    hers, ayesha, khuram, _his, _bilal, _hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    team = Paper()
    pass_over(team, ayesha)

    team.delete_tabs([team.ids["Ayesha Raza"]])
    result = pass_over(team, ayesha)

    assert result["rebuilt"] is True
    assert team.pages["Ayesha Raza"][0] == sheets.APPLIED_COLUMNS
    assert team.column("Ayesha Raza", "Company name") == ["Northwind"]


def test_a_tab_made_by_hand_gets_its_headings(client, manager, on):
    """An empty tab with the right name is not a tab we have written."""
    hers, ayesha, khuram, _his, _bilal, _hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")

    team = Paper(existing=["Ayesha Raza"])
    result = pass_over(team, ayesha)

    assert result["rebuilt"] is True
    assert team.pages["Ayesha Raza"][0] == sheets.APPLIED_COLUMNS


# --------------------------------------------------------------------------- #
# Emptying them
# --------------------------------------------------------------------------- #

def test_reset_empties_both_files_and_writes_them_again(client, manager, on,
                                                        monkeypatch):
    hers, ayesha, khuram, _his, _bilal, _hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    team = Paper(existing=["Somebody's old notes"])
    boss = Paper(existing=["Sheet1"])
    whole_pass(monkeypatch, team, boss)

    reply = client.post("/sheets/reset", headers=manager)

    assert reply.status_code == 200, reply.text
    assert reply.json()["failed"] == []
    assert "Somebody's old notes" in reply.json()["removed"]
    assert "Sheet1" in reply.json()["removed"]
    assert "Somebody's old notes" not in team.tabs()
    assert sheets.PLACEHOLDER not in team.tabs()
    assert sheets.PLACEHOLDER not in boss.tabs()
    assert team.column("Ayesha Raza", "Company name") == ["Northwind"]
    for tab in sheets.MANAGER_TABS:
        assert tab in boss.tabs()


def test_the_blank_tab_stays_if_it_is_all_there_is(client, manager, on):
    """An empty spreadsheet beats a refused request."""
    paper = Paper(existing=[sheets.PLACEHOLDER])
    assert sheets.drop_placeholder(paper) is False
    assert sheets.PLACEHOLDER in paper.tabs()


# --------------------------------------------------------------------------- #
# Pointing it somewhere
# --------------------------------------------------------------------------- #

def test_a_pasted_url_is_stored_as_the_id(client, manager, monkeypatch):
    monkeypatch.setenv("MBS_GOOGLE_CREDENTIALS", "{}")
    reply = client.put("/sheets", headers=manager, json={
        "team_sheet": "https://docs.google.com/spreadsheets/d/1TeamAbc/edit#gid=0",
        "manager_sheet": "https://docs.google.com/spreadsheets/d/1BossXyz/edit"})
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["team_sheet"] == "1TeamAbc"
    assert body["manager_sheet"] == "1BossXyz"
    assert body["team_url"] == "https://docs.google.com/spreadsheets/d/1TeamAbc"
    assert body["configured"] is True


def test_one_file_can_be_set_without_touching_the_other(client, manager, on):
    reply = client.put("/sheets", headers=manager,
                       json={"manager_sheet": "1TheNewManagerFile"})
    assert reply.status_code == 200, reply.text
    assert reply.json()["manager_sheet"] == "1TheNewManagerFile"
    assert reply.json()["team_sheet"] == TEAM


def test_something_that_is_not_a_sheet_is_refused(client, manager):
    reply = client.put("/sheets", headers=manager,
                       json={"team_sheet": "https://example.com/not/a/sheet"})
    assert reply.status_code == 400
    assert "Google Sheet" in reply.json()["detail"]


def test_a_new_team_file_forgets_what_was_written_to_the_old_one(client,
                                                                 manager, on):
    """Otherwise the mirror would think it had already sent the tabs."""
    hers, ayesha, khuram, _his, _bilal, _hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    first = Paper()
    pass_over(first, ayesha)

    client.put("/sheets", headers=manager, json={"team_sheet": "1ADifferentFile"})

    second = Paper()
    result = pass_over(second, ayesha)
    assert result["rebuilt"] is True
    assert second.column("Ayesha Raza", "Company name") == ["Northwind"]


def test_status_lists_both_files_and_every_bd(client, manager, on):
    crew(client, manager)
    body = client.get("/sheets", headers=manager).json()

    assert body["configured"] is True and body["on"] is True
    assert body["team_sheet"] == TEAM
    assert body["manager_sheet"] == BOSS
    assert body["manager_tabs"] == list(sheets.MANAGER_TABS)
    assert sorted(b["tab"] for b in body["bds"]) == ["Ayesha Raza", "Bilal Khan"]


def test_status_says_when_nothing_is_set_up(client, manager, monkeypatch):
    monkeypatch.delenv("MBS_GOOGLE_CREDENTIALS", raising=False)
    monkeypatch.delenv("MBS_SHEET_ID", raising=False)
    monkeypatch.delenv("MBS_MANAGER_SHEET_ID", raising=False)
    body = client.get("/sheets", headers=manager).json()
    assert body["configured"] is False
    assert body["credentials"] is False
    assert body["team_url"] == "" and body["manager_url"] == ""


# --------------------------------------------------------------------------- #
# The switch, and who may press it
# --------------------------------------------------------------------------- #

def test_the_switch_is_off_until_a_manager_turns_it_on(client, manager):
    assert client.get("/settings", headers=manager).json()["sheet_sync"] is False
    assert sheets.one_pass(derived=True, rebuild=False) is None


def test_a_bd_may_not_read_or_run_the_mirror(client, manager):
    make_bd(client, manager, "Ayesha", "ayesha@mbs.co")
    bd = sign_in(client, "ayesha@mbs.co", "secret")
    assert client.get("/sheets", headers=bd).status_code == 403
    assert client.post("/sheets/sync", headers=bd).status_code == 403
    assert client.post("/sheets/reset", headers=bd).status_code == 403
    assert client.put("/sheets", headers=bd,
                      json={"team_sheet": "1Nope"}).status_code == 403


def test_sync_now_refuses_without_a_service_account(client, manager, on,
                                                    monkeypatch):
    monkeypatch.delenv("MBS_GOOGLE_CREDENTIALS", raising=False)
    reply = client.post("/sheets/sync", headers=manager)
    assert reply.status_code == 400
    assert "MBS_GOOGLE_CREDENTIALS" in reply.json()["detail"]


def test_sync_now_refuses_with_no_spreadsheet(client, manager, monkeypatch):
    monkeypatch.setenv("MBS_GOOGLE_CREDENTIALS", "{}")
    monkeypatch.delenv("MBS_SHEET_ID", raising=False)
    monkeypatch.delenv("MBS_MANAGER_SHEET_ID", raising=False)
    client.patch("/settings", headers=manager, json={"sheet_sync": True})
    reply = client.post("/sheets/sync", headers=manager)
    assert reply.status_code == 400
    assert "No spreadsheet yet" in reply.json()["detail"]


def test_sync_now_refuses_while_the_switch_is_off(client, manager, monkeypatch):
    monkeypatch.setenv("MBS_GOOGLE_CREDENTIALS", "{}")
    client.put("/sheets", headers=manager, json={"team_sheet": TEAM})
    reply = client.post("/sheets/sync", headers=manager)
    assert reply.status_code == 400
    assert "switched off" in reply.json()["detail"]


def test_sync_now_runs_a_pass_and_reports_it(client, manager, on, monkeypatch):
    hers, ayesha, khuram, _his, _bilal, _hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")
    team, boss = Paper(), Paper()
    both_files(monkeypatch, team, boss)

    reply = client.post("/sheets/sync", headers=manager)

    assert reply.status_code == 200, reply.text
    assert reply.json()["failed"] == []
    assert team.column("Ayesha Raza", "Company name") == ["Northwind"]
    listed = client.get("/sheets", headers=manager).json()["bds"]
    assert any(b["last_run"] for b in listed)


def test_one_tab_failing_does_not_stop_the_others(client, manager, on,
                                                  monkeypatch):
    hers, ayesha, khuram, _his, _bilal, _hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Northwind", title="Engineer",
        url="https://www.linkedin.com/jobs/view/3912000001")

    class Awkward(Paper):
        def append(self, tab, rows):
            if tab == "Bilal Khan":
                raise RuntimeError("caller does not have permission")
            super().append(tab, rows)

    team, boss = Awkward(), Paper()
    both_files(monkeypatch, team, boss)
    reply = client.post("/sheets/sync", headers=manager)

    assert reply.status_code == 200, reply.text
    assert reply.json()["failed"] == ["Bilal Khan"]
    assert team.column("Ayesha Raza", "Company name") == ["Northwind"]
    listed = {b["name"]: b for b
              in client.get("/sheets", headers=manager).json()["bds"]}
    assert listed["Ayesha Raza"]["last_error"] is None
    assert "permission" in listed["Bilal Khan"]["last_error"]


def test_the_manager_file_failing_is_reported_on_its_own(client, manager, on,
                                                         monkeypatch):
    crew(client, manager)

    class Refusing(Paper):
        def add_tabs(self, names):
            raise RuntimeError("caller does not have permission")

    team, boss = Paper(), Refusing()
    both_files(monkeypatch, team, boss)
    reply = client.post("/sheets/sync", headers=manager)

    assert reply.status_code == 200, reply.text
    assert reply.json()["failed"] == ["the manager's file"]
    assert "Ayesha Raza" in team.tabs()      # the team's file went up regardless


def test_sync_now_can_be_pointed_at_one_bd(client, manager, on, monkeypatch):
    _hers, ayesha, _k, _his, _bilal, _hamza = crew(client, manager)
    team, boss = Paper(), Paper()
    both_files(monkeypatch, team, boss)

    reply = client.post("/sheets/sync", headers=manager,
                        params={"target": f"bd:{ayesha['id']}"})

    assert reply.status_code == 200, reply.text
    assert [one["name"] for one in reply.json()["tabs"]] == ["Ayesha Raza"]
    assert "Bilal Khan" not in team.tabs()
    # One person does not drag the manager's file along with them.
    assert boss.tabs() == {}


# --------------------------------------------------------------------------- #
# What the manager's file says beyond the counts
# --------------------------------------------------------------------------- #

def test_the_overview_says_when_it_was_written(client, manager, on, monkeypatch):
    """A mirror three days stale looks exactly like a fresh one without it."""
    crew(client, manager)
    team, boss = Paper(), Paper()
    whole_pass(monkeypatch, team, boss)

    summary = {r[0]: r[1] for r in boss.pages[sheets.OVERVIEW_TAB] if r[0]}
    assert summary["Last written"].endswith(" UTC")


def test_the_percentages_say_how_much_of_a_list_was_worked(client, manager, on):
    hers, ayesha, khuram, his, bilal, hamza = crew(client, manager)
    # Two finds by Ayesha, so Bilal is handed two and deals with one.
    for n in (1, 2):
        log(client, hers, khuram["id"], company=f"Northwind {n}", title="Engineer",
            url=f"https://www.linkedin.com/jobs/view/391200000{n}")
    handed = client.get(f"/profiles/{hamza['id']}/others", headers=his,
                        params={"status": "pending"}).json()
    client.post(f"/assignments/{handed[0]['assignment_id']}", headers=his,
                json={"status": "applied"})

    with SessionLocal() as db:
        view = sheets.board(db)
    columns, rows = sheets.exports.bd_table(view)
    seats = {row[0]: dict(zip(columns, row)) for row in rows}

    # Bilal was given two and has dealt with one of them.
    assert seats["Bilal Khan"]["Others' given"] == 2
    assert seats["Bilal Khan"]["Dealt with %"] == 50
    # Three applications in all; two of them Ayesha's.
    assert seats["Ayesha Raza"]["Share of applied %"] == 67
    assert seats["Bilal Khan"]["Share of applied %"] == 33


def test_a_percentage_of_nothing_is_blank_not_zero(client, manager, on):
    """A chart skips an empty cell and draws a nought."""
    assert sheets.exports.percent(0, 0) == ""
    assert sheets.exports.percent(1, 4) == 25

    make_bd(client, manager, "Adnan", "adnan@mbs.co")
    with SessionLocal() as db:
        view = sheets.board(db)
    columns, rows = sheets.exports.bd_table(view)
    assert rows == []          # nobody holds a profile, so nobody has a seat yet


def test_the_by_day_tab_is_a_column_per_bd_and_a_row_per_day(client, manager, on,
                                                             monkeypatch):
    hers, ayesha, khuram, his, bilal, hamza = crew(client, manager)
    log(client, hers, khuram["id"], company="Monday", title="Engineer",
        applied_on="2026-09-14",
        url="https://www.linkedin.com/jobs/view/3912000001")
    log(client, his, hamza["id"], company="Wednesday", title="Engineer",
        applied_on="2026-09-16",
        url="https://www.linkedin.com/jobs/view/3912000002")

    team, boss = Paper(), Paper()
    whole_pass(monkeypatch, team, boss)

    rows = boss.pages[sheets.DAY_TAB]
    assert rows[0] == ["Date", "Ayesha Raza", "Bilal Khan", "Everyone"]
    # The Tuesday between them is filled in, so a chart does not join the two.
    assert [r[0] for r in rows[1:]] == ["2026-09-14", "2026-09-15", "2026-09-16"]
    assert [r[-1] for r in rows[1:]] == [1, 0, 1]
    assert boss.column(sheets.DAY_TAB, "Ayesha Raza") == [1, 0, 0]
    assert boss.column(sheets.DAY_TAB, "Bilal Khan") == [0, 0, 1]


def test_the_by_day_tab_is_empty_when_nothing_has_happened(client, manager, on,
                                                           monkeypatch):
    crew(client, manager)
    team, boss = Paper(), Paper()
    whole_pass(monkeypatch, team, boss)
    assert boss.pages[sheets.DAY_TAB] == [["Date", "Everyone"]]
