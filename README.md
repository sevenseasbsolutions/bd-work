# MBS

A job-dispatch board, cut down to the part that matters.

A BD finds a job and applies for it under one of their profiles. The same
second, that posting lands on every other live profile's list as an **others'
job** — theirs to apply for or turn down. A manager adds the people, adds the
profiles, says who runs which, and reads the numbers.

That is the whole product. There is no cycle to open or close (the workspace is
always open), no interview, no assessment, no developer side and no client
record.

A team arriving with three months of history in a spreadsheet uploads it, and
it becomes exactly that: own jobs for the profile it is uploaded against, and
others' jobs for everybody else.

## The five words

Used identically in the database, the API and on every screen, so a manager and
a BD can never mean two different things by them:

| | |
|---|---|
| **own job** | a job this profile went out and found, and applied for itself |
| **others' job** | a job another profile found, handed to this one to apply for |
| **pending** | an others' job sitting on this profile's list, not yet dealt with |
| **skipped** | an others' job this profile looked at and turned down |
| **applied** | own jobs plus others' jobs applied for — everything sent |
| **all jobs** | the pool, with this profile's standing against every row |

## Screens

**BD** — one screen. A rail of the profiles assigned to them; for each one,
three tabs: Own jobs (with the sheet importer and the entry grid below),
Others' jobs (Pending jobs / Applied / Skipped, with Applied and Skip buttons,
and a tick box on every row), and All jobs — every row of which has a **Copy**
button that puts the whole row on the clipboard, tab-separated, ready to paste
straight into Excel. The toolbar's **Copy all** takes everything on screen,
filters included, with a header line.

**Manager** — Overview (the five counts per BD and per profile), People (add
people, add profiles, assign, switch off, delete, keep the job-platform list,
set what BDs may do and run the Google Sheet mirror), All jobs (the pool from
above), and Profiles, which is the BD screen read-only for any profile.

## Bringing an old sheet across

**Own jobs › Import a sheet.** Drop in an `.xlsx` or a `.csv` and every line
becomes a job that profile found and applied for — which means every line also
lands on every other live profile's list as an others' job. It is the entry
grid's own code path, not a second way into the pool.

Columns can be in any order and the header row does not have to be the first
row: a sheet with a title and a blank line above the headings reads fine.
Alongside the six the system writes — Company name, Job title, Job link, Job
platform, Email, Date — the spellings people actually use are understood:
Client, Role, Link, Portal, Applied on and a couple of dozen more. A real Excel date comes out as a day rather than a timestamp, and a
link hidden behind the word "Apply" is read off the hyperlink. **Download
template** hands back an empty sheet with the right headings and a page
explaining them.

Afterwards, five numbers, and they add up to the number of lines read out of the
file — exactly:

| | |
|---|---|
| **added** | new to the pool; everybody else has it on their list now |
| **already in the pool** | a colleague had found it; this profile joins it |
| **already on this profile** | on record before the upload, left alone |
| **repeated within the sheet** | the same posting on two lines of one file |
| **could not be read** | no link, no company and no job title |

That equality is the feature. "2,750 of my 3,000 went in" is followed by where
the other 250 are, and the ones that did not go in download as a sheet — with
the line number and the reason — to fix and send again.

Every line is marked applied. A Status column is ignored — Skipped, Pending,
Not applied and all — because a line held back is data missed; put in the
sheet only what the profile really applied for.

A tab from the team's Google Sheet uploads as it is: Applied on, Company name,
Job title, Job link, Job platform and Email are read; BD, Own or others and
Found by are ignored, and Filed at stands in for a blank Applied on. Upload the
whole downloaded workbook and only the tab named after the profile is read, so
nobody files a colleague's work as their own. The template has the same six
columns in the same order.

Dates are settled to YYYY-MM-DD on the way in, so the date window, the counts
and the Google Sheet all read the same day. `03/04/2026` is read the way the
rest of the file reads: one line with a first number over 12 makes the file
day-first, one with a second number over 12 makes it month-first. A line whose
date cannot be read still goes in (counting against the upload day), the
report says how many, and uploading the fixed file fills the date in.

**Uploading twice is safe, and it is the answer to a sheet that half-arrived.**
A posting is its fingerprint, so anything already on this profile's record is
counted and skipped; the import commits in batches as it goes, so a run cut off
at line 1,400 keeps 1,400. Upload the same file again and only what is missing
is added. Three thousand lines across five profiles takes about seven seconds;
the same file a second time, under three.

Every upload is kept against the profile with its counts, so what went in on
which day is a list rather than a memory.

## Select all

An imported sheet is the reason this exists: three months of one BD's work is
three months of others' jobs on everybody else's list, and nothing that size
gets dealt with a row at a time.

A tick box on every row of Others' jobs and one at the head of the list. Tick
what you want — or the whole list — and **Applied** or **Skip** moves all of it
in a single request. On the Applied and Skipped lists the same selection
**Undo**s back to pending. The selection is cleared whenever the list under it
changes (another tab, another profile, another date range), because a tick that
outlived its list is a press nobody can predict the result of.

The manager owns whether it is there at all: **People › What BDs may do**.
Switched off, the boxes go and the server refuses the request — the Applied and
Skip buttons on each row are then the only way. It is a switch about doing it
wholesale, not about doing it.

## Exporting

The **Export** button sits at the right-hand end of the date-range strip, on
every screen that has one, because what it hands you is exactly the window that
control is set to — right down to the filename
(`MBS workspace 2026-09-15-to-2026-09-16.xlsx`).

A BD exports the profile they are looking at: **Summary** (its five counts),
**Own jobs**, **Others' jobs** (all three statuses on one sheet, because the
question a spreadsheet gets asked is "what happened to everything handed to
me"), and **All jobs**. A manager exports the whole workspace: **Summary**,
**By BD**, **By profile**, **All jobs** and **People** — and can export any one
profile from the Profiles screen.

Every sheet has a frozen, filterable header row, columns sized to their
contents, and the job link as a real hyperlink rather than blue text nobody can
click.

## The Google Sheet

Export is a button somebody presses. This is the same rows without anybody
pressing anything: a BD applies for a job and it is on their tab about five
seconds later, which is what a manager who lives in spreadsheets actually wants.

It is not the same request. The application saves to MBS the instant it is made;
a timer carries it up on its next pass. Sheets allows sixty writes a minute, so
an application that called Google itself would put a three-thousand-line import
into three thousand calls and have the BD waiting on Google before their row
saved. Batched, that same import is about two calls, and the grid never waits at
all.

It goes **one way**, and that is a decision rather than a shortcut. A row in a
spreadsheet has no fingerprint and no id, so a sheet that could be edited back
into the pool would be a workspace that disagrees with itself. The ways in stay
what they were — the entry grid and the sheet importer, both through `log_find`,
both deduping. The sheet is a mirror.

### One file, a tab each

One spreadsheet for the whole workspace. Every profile gets a tab of its own,
named after it, carrying **everything that profile has applied for** — its own
finds and the others' jobs it took on, which is exactly the "applied" of the
five words. A pending row is not on it because nobody has applied for it yet,
and a skipped one never will be.

| tab | what is on it |
|---|---|
| `Khuram — AI Engineer` | Applied on · Company name · Job title · Job link · Job platform · Email · Own or others · Found by · Filed at |
| `Zahid — ML Engineer` | the same, for that profile |
| `Manager — Overview` | the counts behind "Where the work is" |
| `Manager — By BD` | the five counts per BD, their profiles added together |
| `Manager — By profile` | the five counts per profile |
| `Manager — All jobs` | the pool |

A tab per profile rather than per person, because the profile is the unit of
work: one BD running two identities is two candidates to a client, and their
work does not belong on one list. The manager's four are prefixed so they sort
together and can never collide with a profile called "All jobs".

**A profile added this afternoon has a tab within five seconds** and fills it as
they work. Nothing is configured per person — the tab list is the profile list.
Rename a profile and its tab is renamed with it, rows intact; delete its tab by
hand and the next pass writes it again from nothing.

The manager's four are rewritten whole every few minutes, because they are
answers rather than events: a count that went down cannot be appended. The
profile tabs are appended to, which is what makes them quick.

### Undo is why appending is not enough

Turning an others' job back to pending deletes its application, and a tab that
only ever appends cannot take a row back. So every pass asks the database two
things about the rows it believes are up there — how many there are, and when
the newest of them was filed — and writes the tab again from scratch when either
has moved. One query, cheap enough to do every time, and the rare thing pays for
itself instead of every cycle paying for it.

The stamp is there as well as the count because of SQLite: it hands back the
highest `rowid` it has just freed, so deleting the newest application and filing
another one between two passes can produce a row carrying the id of the one that
went — the count identical, the new row invisible to anything watching ids
alone. Its filing time is later, which is what gives it away. Behind all of it
sits a slower unconditional rebuild, for anything odder: a process killed
between the rows landing in Google and the watermark being committed here.

### What goes on a tab, and what does not

Two switches, because they are two decisions. **Mirror work into it** turns the
thing on. **Uploaded sheets too** says whether an imported sheet goes up with
the work being typed today, and it ships **off**.

Off, a profile's tab is what they are finding now: a line somebody pressed
**+ New entry** for, and nothing else. A BD bringing three months of history
across does not bury today under thousands of old rows. Switch it on and the
next pass carries that history up; switch it off again and those rows come back
out — the same drift check that handles an undo notices that what belongs on the
tab has changed.

Applying for an imported posting is not an import. The row that lands when a
colleague presses **Applied** is somebody working today, so it goes up with the
switch off: what is held back is the upload, not what people do with it.

And it is a switch about the profile tabs only. An imported row **is** an own
job — the manager's four count it as one whatever this is set to, because a
manager reading the sheet and a manager reading the Overview screen must not be
given two different totals.

### Turning it on

1. In Google Cloud, make a **service account** and download its JSON key. Enable
   the **Google Sheets API** on the project. An API key will not do: Google
   answers a write with *"API keys are not supported by this API"*, and an OAuth
   client ID needs a human clicking Allow in a browser. A service account has an
   identity of its own, which is what a timer at 3am needs.
2. **Share the spreadsheet with the service account's email**
   (`…@….iam.gserviceaccount.com`) as an **Editor**. Nothing works until this is
   done, and the error when it is not says `caller does not have permission`.
3. Set `MBS_GOOGLE_CREDENTIALS` — the path to that JSON file, or the JSON itself
   for a host that only offers environment variables.
4. **People › The Google Sheet**: paste the spreadsheet link, press Save, and
   switch the mirror on. Both are stored, so neither needs a deploy.
   `MBS_SHEET_ID` sets the same thing from the environment if you would rather
   say it once at boot.

The tabs are made on the first pass; an empty spreadsheet is the right thing to
point it at, and any other tab in the same file is left alone until somebody
presses **Empty and rewrite**. The manager's top bar carries a **Google Sheet ↗**
link on every screen, so the file is one click away from wherever they are.

`GET /sheets` reports whether it is pointed anywhere and switched on, then one
entry per profile: which tab, how many rows, when it last ran and what went
wrong if anything did. `PUT /sheets` points it at a spreadsheet.
`POST /sheets/sync` runs a pass now, `?target=profile:7` over one profile, and
`?rebuild=true` writes every tab again from nothing. `POST /sheets/reset` empties
the file and rebuilds it. A 200 is not a promise that every tab was written: the
reply names the ones that were not, because **one profile's tab failing must not
stop the other five**.

Three intervals, because the three cost different amounts:

| variable | default | |
|---|---|---|
| `MBS_SHEET_INTERVAL` | `5` | seconds between appends — how live the live tabs are |
| `MBS_SHEET_REWRITE` | `300` | seconds between rewrites of the manager's four |
| `MBS_SHEET_REBUILD` | `3600` | seconds between unconditional rebuilds of every tab |

Values are written as text, never as formulas. A client called `=Dyson` is a
client called `=Dyson`, and a BD cannot put a formula in the manager's
spreadsheet by typing one into the entry grid.

One pass runs at a time. The timer has a thread of its own and the buttons run
in the API's threadpool, and without that lock a **Sync now** pressed mid-pass
has two writers holding two snapshots of the same tab list — the second one to
create a tab being told it already exists.

## Searching

The search box on either All jobs screen matches the job title, the client, who
found it — and the **link**. The link is the one thing about a posting that is
unambiguous: two people will write a client's name three ways, but they are
holding the same URL.

Paste a whole address and it matches the row even when the copy in your address
bar carries a referral tail the stored one does not. The protocol, the www, the
fragment and every tracking parameter are dropped from both sides before they
are compared — but parameters that *name* the posting are kept, because on
Indeed, ADP and Workday the job id lives nowhere else, and dropping the query
there would make every posting on the site look like the same one. Typing a
bare job id (`~017acdef…`, `jk=77aa`) or a bare host works too.

## From this day to that day

Both sides have the same range strip above their content: **All time**, **Last
7 days**, **Last 30 days**, **This month**, or two date boxes for anything
else. It is one window read by everything on the screen at once — the lists,
the tiles above them and the manager's totals — so a filtered list can never
sit under an unfiltered number.

What counts as a row's day:

| | |
|---|---|
| an own job | the date in its entry line, or when it was filed if that date cannot be read |
| an others' job | when it was applied for or turned down, or when it was handed over if neither |
| a posting in All jobs | when it was first seen |

The date column is free text — somebody backfilling yesterday types what they
type — so the day is worked out in Python rather than compared in SQL.
`2026-09-14`, `14/09/2026`, `14 Sep 2026` and `Sep 14, 2026` are all read;
anything unreadable falls back to the timestamp the row was filed at, which is
never wrong, only less precise than what was meant.

## Logging a find

Press **+ New entry** and a line opens. Six columns, in the order the work
happens in:

    Company name · Job title · Job link · Job platform · Email · Date

**Job platform** is a dropdown the manager fills in on the People screen — add
a board, retire one, and the grid offers the new list straight away. Retiring a
board only changes what the dropdown offers next time: a job stores the text
that was chosen, not a reference, so nothing recorded last month changes
because a board was dropped today.

The last two fill themselves in — **Date** is stamped with today, and **Email**
carries over from the line before, because people apply from one inbox all
morning. Both stay editable.

Pressing **+ New entry** again files the line and opens the next one; **Enter**
on the last line does the same, so a run of entries never needs the mouse.
Nothing reaches the server until you do one of those or press **Save now**.
A block pasted from Excel fills across and down from the cell it lands in,
growing the grid — which is the other half of the Copy button on All jobs:
what comes out pastes back in.

The **email is on the entry, not on the profile and not on the job**: one
identity does not always apply from one inbox, and two profiles applying to the
same posting each used their own.

## Running it

Needs Python 3.11+ and Node 18+.

```bash
# backend — http://127.0.0.1:8000
cd backend
python -m venv .venv && .venv/Scripts/activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python seed.py                                       # optional demo workspace
uvicorn app.main:app --reload

# frontend — http://127.0.0.1:5174
cd frontend
npm install
npm run dev
```

The database is a SQLite file at `backend/mbs.db`, made on first boot. Point
`MBS_DATABASE_URL` at Postgres and the same models apply unchanged.

On an empty database the first boot mints one manager account, from
`MBS_ADMIN_EMAIL` / `MBS_ADMIN_PASSWORD` (default `manager@mbs.co` / `manager`).
Sign in, change the password, clear the variables.

`python seed.py --reset` throws the database away and builds the demo
workspace: a manager, three BDs, five profiles and seven postings already
dispatched between them. Everyone signs in with `mbs`, the manager with
`manager`.

### Settings

| variable | default | |
|---|---|---|
| `MBS_DATABASE_URL` | `sqlite:///backend/mbs.db` | any SQLAlchemy URL |
| `MBS_SECRET` | a development value | **set this in production** — it signs the tokens |
| `MBS_ADMIN_EMAIL` | `manager@mbs.co` | the first account, made only on an empty database |
| `MBS_ADMIN_PASSWORD` | `manager` | |
| `VITE_API` | `http://127.0.0.1:8000` | where the frontend looks for the API |
| `MBS_SHEET_ID` | — | the one spreadsheet, if you would rather set it here than on the People screen |
| `MBS_GOOGLE_CREDENTIALS` | — | the service account: a path to its JSON key, or the JSON |

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

156 tests. Nothing is mocked: every one runs the real routes against a real
database. The single stand-in anywhere is in `test_sheets.py`, where Google is
a spreadsheet made of Python lists — the same four methods `GoogleSheet` has,
doing what a spreadsheet does with them, rather than a recording of what the
API was expected to be asked.

- `tests/test_matching.py` — the fingerprint rules on their own
- `tests/test_flow.py` — the real routes against a real database: sign-in,
  permissions, dispatch, apply, skip, undo, the entry line, and every count on
  the manager's screen
- `tests/test_window.py` — the date shapes people type, and the range narrowing
  a list and the total above it to the same number
- `tests/test_platforms.py` — the manager's board list, and that retiring one
  leaves the jobs recorded against it alone
- `tests/test_exports.py` — the workbooks, read back with openpyxl: the sheets,
  the counts, the hyperlinks, the date window, who may export what, and a
  filename with an em dash in it surviving the HTTP header
- `tests/test_imports.py` — uploading an old sheet: the headings people
  really type, a header row that is not the first row, real Excel dates, a
  link behind the word "Apply", a CSV, every line accounted for, the leftovers
  workbook, and the same file twice adding only what is missing
- `tests/test_bulk.py` — Select all: one press moving a whole list either way,
  the counts moving with it, one row that is not yours stopping the press, and
  the manager's switch stopping it from the server rather than from the button
- `tests/test_sheets.py` — the Google Sheet mirror, against a spreadsheet made
  of lists: a tab per profile carrying only what that profile applied for, an
  others' job reaching the tab of whoever took it, a pending or skipped one
  never reaching any, a profile added mid-afternoon getting a tab on the next
  pass, a rename taking its tab with it, a tab deleted or hand-made getting
  its headings, Undo taking a row back off, the manager's four matching the
  Overview screen, emptying the file and writing it again, and one tab failing
  leaving the others written
- `tests/test_schema.py` — a database missing a column gets it back, and an
  upgrade reads every row it already had as typed rather than imported

## How it is put together

```
backend/app/
  db.py         engine, session, Base
  models.py     users, profiles, platforms, jobs, applications, assignments
  schema.py     adds columns a later version introduced, at boot
  matching.py   what makes two pasted links the same posting — pure functions
  dispatch.py   the pool: a find fans out, the three lists and the date window
  imports.py    an old sheet read into rows, and those rows filed as finds
  settings.py   the manager's switches, with their defaults
  security.py   bcrypt and JWT
  exports.py    the .xlsx workbooks, the import template and the leftovers file
  sheets.py     the same rows, mirrored into one Google Sheet on a timer —
                a tab per profile, four for the manager
  main.py       every route
frontend/src/
  api.js        one fetch wrapper; one place the token and a 401 are handled
  App.jsx       the shell — who is signed in and which screen they are on
  views/        Login, BdWork (the three lists), EntryGrid (+ New entry),
                SheetImport (an old sheet), Overview, People (incl. job
                platforms and the switches), Pool, ui
  styles.css    the design system: one neutral ramp, one accent, dark included
```

### Two rules worth knowing before changing anything

**An application is unique per (job, profile), not per (job, user).** One
person's two profiles are two different candidates to a client and may both
apply for the same posting. Only the same identity twice is forbidden.

**An import is not a special case.** Every line of an uploaded sheet goes
through `log_find`, the same function the entry grid's + New entry calls. That
is what makes an upload dedupe, fan out and count like typing would — and what
means a fix to any of those is a fix in one place.

**A posting is its fingerprint, not its URL.** `matching.py` reads a platform's
own job id where there is one, falls back to the canonical URL — tracking
parameters dropped, job-id parameters kept — and to the client and role as
written only when there is no link at all. It also merges a listing with its
own apply flow, so the colleague who pasted the listing and the colleague who
pasted whatever the apply button left in the address bar are on one row.

### Things that happen without anybody pressing a button

- A new profile is handed the pool that already exists, so it does not start
  empty and wait a week for somebody else's find.
- A profile switched off gives back the work it never got to; switched back on,
  it catches up on everything found while it was away.
- Logging a find for a job already sitting on your own waiting list closes that
  row off, for the BD who applied without touching the button.
- Removing a find nobody else has applied for withdraws the posting from
  everybody's list — a typo dispatched to eight profiles has to be undoable.
  Once one colleague has applied, the posting stays; only your claim goes.
- A column added to the models in a later version is added to an existing
  database on the next boot, with its default, so an upgrade does not need the
  data thrown away. See `schema.py` — it only ever ADDs.
