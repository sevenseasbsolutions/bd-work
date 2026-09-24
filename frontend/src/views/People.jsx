/* Who signs in, which identities exist, and who runs which.
 *
 * The manager's only writing screen. Everything else in MBS is a list of
 * something that happened.
 */
import React, { useState } from "react";
import { api } from "../api.js";
import { Chip, Danger, Field, State, useLoad, useToast } from "./ui.jsx";

export default function People() {
  const users = useLoad(() => api.users(), []);
  const profiles = useLoad(() => api.profiles(), []);
  const reload = () => { users.reload(); profiles.reload(); };

  return (
    <>
      <Team users={users} onChange={reload} />
      <Identities profiles={profiles} users={users.data || []} onChange={reload} />
      <Platforms />
      <Switches />
      <SheetMirror />
    </>
  );
}

/* ── Switches ─────────────────────────────────────────────────────────── */

/** What the whole team is allowed to do, decided in one place.
 *
 * There is one switch so far and it earns its place: after a BD imports three
 * months of a spreadsheet, every other profile has thousands of others' jobs
 * waiting, and Select all is the only way through them that is not a
 * afternoon of clicking. Which is also exactly why a manager might want it
 * off — one press turning three thousand rows into "skipped" is a real
 * decision, and some teams want it made a row at a time.
 *
 * Switching it off hides the boxes and stops the request. The buttons on each
 * row are untouched: this is about doing it wholesale, not about doing it.
 */
function Switches() {
  const state = useLoad(() => api.settings(), []);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const on = state.data?.select_all !== false;

  async function flip() {
    setBusy(true);
    try {
      const saved = await api.saveSettings({ select_all: !on });
      toast(saved.select_all
        ? "Select all is on. BDs can apply for or skip a whole list in one press."
        : "Select all is off. BDs deal with others' jobs a row at a time.");
      state.reload();
    } catch (e) {
      toast(e.message, "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <header>
        <h2>What BDs may do</h2>
        <span className="muted small">Set once, for everybody.</span>
      </header>

      <State busy={state.first} error={state.error}>
        <div className="wrap-row">
          <div style={{ flex: "1 1 320px", minWidth: 240 }}>
            <div className="row" style={{ gap: "var(--s2)" }}>
              <span className="strong">Select all on others&apos; jobs</span>
              <Chip kind={on ? "applied" : "off"}>{on ? "on" : "off"}</Chip>
            </div>
          </div>
          <span className="spacer" />
          <button className="btn" disabled={busy} onClick={flip}>
            {busy ? "Saving…" : on ? "Switch off" : "Switch on"}
          </button>
        </div>
      </State>
    </div>
  );
}

/* ── The Google Sheet ─────────────────────────────────────────────────── */

/** The mirror, and the only place it is turned on.
 *
 *  Two different things are shown as one line each, because they fail
 *  differently and a manager needs to tell them apart: whether MBS has been
 *  pointed at a spreadsheet at all (a deploy job, two environment variables),
 *  and whether the team wants it running (a switch, flipped on a Tuesday).
 *  A switch that is on and has nowhere to write is the confusing state, so the
 *  button is not offered until there is somewhere.
 */
function SheetMirror() {
  const state = useLoad(() => api.sheetStatus(), []);
  const switches = useLoad(() => api.settings(), []);
  const [busy, setBusy] = useState("");
  const toast = useToast();

  const it = state.data || {};
  const on = !!it.on;
  const imports = switches.data?.sheet_sync_imports === true;

  async function run(what, job, said) {
    setBusy(what);
    try {
      const done = await job();
      toast(typeof said === "function" ? said(done) : said);
    } catch (e) {
      toast(e.message, "bad");
    } finally {
      setBusy("");
      // Reloaded either way. A failed press is the one where the card has
      // something new to say — the server has just recorded what Google
      // refused, and a toast that has faded is not somewhere to read it.
      state.reload();
      switches.reload();
    }
  }

  const flip = () => run("flip",
    () => api.saveSettings({ sheet_sync: !on }),
    (saved) => saved.sheet_sync
      ? "The Google Sheet is on. New work appears in it within five seconds."
      : "The Google Sheet is off. Nothing more will be written to it.");

  const flipImports = () => run("imports",
    () => api.saveSettings({ sheet_sync_imports: !imports }),
    (saved) => saved.sheet_sync_imports
      ? "Uploaded sheets go up too. The next pass carries the history across."
      : "Uploaded sheets stay out. Only what BDs type from now on goes up.");

  const sync = (rebuild) => run(rebuild ? "rebuild" : "sync",
    () => api.syncSheet(rebuild),
    (done) => done.failed?.length
      ? `Written, except: ${done.failed.join(", ")}. See below.`
      : `${done.tabs.length} tab${done.tabs.length === 1 ? "" : "s"} written.`);

  const reset = () => run("reset",
    () => api.resetSheet(),
    (done) => `Emptied and written again — ${done.removed.length} old tab`
      + `${done.removed.length === 1 ? "" : "s"} removed.`);

  return (
    <div className="card">
      <header>
        <h2>The Google Sheets</h2>
        <span className="muted small">
          One file for the team, one for you. Written on their own.
        </span>
      </header>

      <State busy={state.first} error={state.error}>
        {!it.credentials && (
          <p className="muted small" style={{ margin: "0 0 var(--s3)" }}>
            No service account yet. MBS needs one Google service account with
            edit access to both files, and <code>MBS_GOOGLE_CREDENTIALS</code>{" "}
            set on the server. One account covers both. See the README.
          </p>
        )}

        <SheetBox
          title="The team's file" busy={busy} disabled={!it.credentials}
          value={it.team_sheet} url={it.team_url}
          onSave={(link) => run("team", () => api.setSheets({ team_sheet: link }),
                                "Pointed at that file. Every tab from nothing.")} />

        <SheetBox
          title="The manager's file" busy={busy} disabled={!it.credentials}
          value={it.manager_sheet} url={it.manager_url}
          onSave={(link) => run("boss", () => api.setSheets({ manager_sheet: link }),
                                "Pointed at that file.")} />

        <div className="wrap-row" style={{ marginTop: "var(--s4)" }}>
          <div style={{ flex: "1 1 320px", minWidth: 240 }}>
            <div className="row" style={{ gap: "var(--s2)" }}>
              <span className="strong">Mirror work into them</span>
              <Chip kind={on && it.configured ? "applied" : "off"}>
                {on ? "on" : "off"}
              </Chip>
            </div>
          </div>
          <span className="spacer" />
          <div className="row" style={{ gap: "var(--s2)" }}>
            {on && it.configured && (
              <>
                <button className="btn" disabled={!!busy} onClick={() => sync(false)}>
                  {busy === "sync" ? "Sending…" : "Sync now"}
                </button>
                <button className="btn" disabled={!!busy} onClick={() => sync(true)}
                        title="Write every tab again from nothing">
                  {busy === "rebuild" ? "Writing…" : "Rebuild"}
                </button>
              </>
            )}
            <button className="btn" disabled={!!busy || !it.configured} onClick={flip}>
              {busy === "flip" ? "Saving…" : on ? "Switch off" : "Switch on"}
            </button>
          </div>
        </div>

        {/* The second decision, and only worth showing once the first is made:
            what a mirror does with an uploaded sheet is a question about a
            mirror that is running. */}
        {on && it.configured && (
          <div className="wrap-row" style={{ marginTop: "var(--s4)" }}>
            <div style={{ flex: "1 1 320px", minWidth: 240 }}>
              <div className="row" style={{ gap: "var(--s2)" }}>
                <span className="strong">Uploaded sheets too</span>
                <Chip kind={imports ? "applied" : "off"}>{imports ? "on" : "off"}</Chip>
              </div>
              <p className="muted small" style={{ margin: "4px 0 0" }}>
                With this off, only what a BD types into the entry grid reaches
                their tab — somebody bringing three months of history across
                does not bury today&apos;s work under thousands of old rows.
                Switch it on and the next pass carries that history up; switch
                it off again and those rows come back out. Either way your file
                is unchanged: an imported row is an own job, and every total
                says so.
              </p>
            </div>
            <span className="spacer" />
            <button className="btn" disabled={!!busy} onClick={flipImports}>
              {busy === "imports" ? "Saving…" : imports ? "Switch off" : "Switch on"}
            </button>
          </div>
        )}

        {it.configured && (it.bds || []).length > 0 && (
          <div style={{ marginTop: "var(--s5)" }}>
            <span className="strong">Who has a tab</span>
            <div className="scroll" style={{ marginTop: "var(--s2)" }}>
              <table>
                <thead>
                  <tr><th>Tab</th><th className="num">Rows</th>
                    <th>Last written</th></tr>
                </thead>
                <tbody>
                  {(it.bds || []).map((b) => (
                    <tr key={b.target}>
                      <td className="strong">{b.tab}</td>
                      <td className="num">{b.rows}</td>
                      <td className="muted small">
                        {b.last_error
                          ? <span style={{ color: "var(--bad-text)" }}>
                              failed — {b.last_error}
                            </span>
                          : b.last_run ? b.last_run.replace("T", " ") : "not yet"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row" style={{ marginTop: "var(--s3)" }}>
              <span className="spacer" />
              <Danger title="Removes every tab in both spreadsheets, then writes MBS's again."
                      onConfirm={reset}>
                {busy === "reset" ? "Emptying…" : "Empty and rewrite"}
              </Danger>
            </div>
          </div>
        )}
      </State>
    </div>
  );
}

/** One spreadsheet: what it is for, where it is, and a box to move it.
 *
 *  The box holds what is being typed and only what comes back from the server
 *  is shown as saved — so a link pasted and not saved never reads as if it is
 *  live, and one the server rejected does not linger looking accepted.
 */
function SheetBox({ title, value, url, onSave, busy, disabled }) {
  const [typed, setTyped] = useState(null);
  const link = typed === null ? (value || "") : typed;
  const changed = typed !== null && typed.trim() !== (value || "");

  function save() {
    onSave(typed.trim());
    setTyped(null);
  }

  return (
    <div style={{ marginTop: "var(--s4)" }}>
      <div className="row" style={{ gap: "var(--s2)" }}>
        <span className="strong">{title}</span>
        <Chip kind={value ? "applied" : "off"}>{value ? "set" : "not set"}</Chip>
      </div>
      <div className="row" style={{ gap: "var(--s2)", marginTop: "var(--s2)" }}>
        <input value={link} disabled={disabled || !!busy}
               placeholder="paste the Google Sheet link"
               style={{ flex: "1 1 260px", minWidth: 200 }}
               onChange={(e) => setTyped(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter" && changed) save(); }} />
        <button className="btn" disabled={!changed || !!busy} onClick={save}>
          Save
        </button>
      </div>
      {url && !changed && (
        <p className="small" style={{ margin: "6px 0 0" }}>
          <a href={url} target="_blank" rel="noreferrer">Open it</a>
        </p>
      )}
    </div>
  );
}

/* ── Job platforms ────────────────────────────────────────── */

/** The boards the entry grid offers. Kept in the database rather than in the
 *  code, so adding one is something a manager does on a Tuesday afternoon
 *  rather than something that needs a release. */
function Platforms() {
  const rows = useLoad(() => api.platforms(), []);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function add(event) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.addPlatform(name.trim());
      toast(`${name.trim()} is on the list.`);
      setName("");
      rows.reload();
    } catch (e) {
      toast(e.message, "bad");
    } finally {
      setBusy(false);
    }
  }

  async function remove(row) {
    try {
      const reply = await api.removePlatform(row.id);
      // Worth saying out loud: a manager retiring a board wants to know it has
      // not quietly rewritten what people already recorded against it.
      toast(reply.jobs_keeping_it
        ? `${row.name} taken off the list. ${reply.jobs_keeping_it} job${reply.jobs_keeping_it === 1 ? "" : "s"} already recorded on it keep it.`
        : `${row.name} taken off the list.`);
      rows.reload();
    } catch (e) {
      toast(e.message, "bad");
    }
  }

  return (
    <div className="card">
      <header>
        <h2>Job platforms</h2>
        <span className="muted small">
          What the Job platform box offers when a BD logs a find.
        </span>
      </header>

      <form onSubmit={add} className="wrap-row" style={{ marginBottom: "var(--s4)" }}>
        <div style={{ flex: "0 1 260px", minWidth: 180 }}>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)}
                 placeholder="Toptal" aria-label="Platform name" required />
        </div>
        <button className="btn primary" disabled={busy || !name.trim()}>
          {busy ? "Adding\u2026" : "Add platform"}
        </button>
      </form>

      <State busy={rows.first} error={rows.error}
             empty={(rows.data || []).length === 0
               && "No platforms. The Job platform box stays empty until you add one."}>
        <div className="wrap-row">
          {(rows.data || []).map((row) => (
            <span key={row.id} className="pill">
              {row.name}
              <Danger title="Take this off the dropdown. Jobs already recorded on it keep it."
                      onConfirm={() => remove(row)}>&times;</Danger>
            </span>
          ))}
        </div>
      </State>

      <p className="muted small" style={{ marginTop: "var(--s3)", marginBottom: 0 }}>
        Removing one only changes what the dropdown offers next time. A job
        stores the text that was chosen, so nothing already recorded changes.
      </p>
    </div>
  );
}

/* ── People ───────────────────────────────────────────────────────────── */

const NEW_PERSON = { name: "", email: "", password: "", role: "bd" };

function Team({ users, onChange }) {
  const [form, setForm] = useState(NEW_PERSON);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  async function add(event) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.addUser({ ...form, name: form.name.trim(), email: form.email.trim() });
      toast(`${form.name.trim()} can sign in now.`);
      setForm(NEW_PERSON);
      onChange();
    } catch (e) {
      toast(e.message, "bad");
    } finally {
      setBusy(false);
    }
  }

  async function act(run, said) {
    try {
      await run();
      toast(said);
      onChange();
    } catch (e) {
      toast(e.message, "bad");
    }
  }

  return (
    <div className="card">
      <header>
        <h1>Add Roles of Employee</h1>
        <span className="muted small">Roles are BD, Manager</span>
      </header>

      <form onSubmit={add} style={{ marginBottom: "var(--s5)" }}>
        <div className="grid">
          <Field label="Name" value={form.name} onChange={set("name")}
                 placeholder="Ayesha Raza" required />
          <div className="field">
            <label>Email</label>
            <input type="email" value={form.email} onChange={set("email")}
                   placeholder="ayesha@mbs.co" required />
          </div>
          <div className="field">
            <label>Password</label>
            <input type="text" value={form.password} onChange={set("password")}
                   placeholder="at least 4 characters" required />
          </div>
          <div className="field">
            <label>Role</label>
            <select value={form.role} onChange={set("role")}>
              <option value="bd">BD</option>
              <option value="manager">Manager</option>
            </select>
          </div>
        </div>
        <div className="row" style={{ marginTop: "var(--s3)" }}>
          <span className="spacer" />
          <button className="btn primary" disabled={busy}>{busy ? "Adding…" : "Add person"}</button>
        </div>
      </form>

      <State busy={users.first} error={users.error}
             empty={(users.data || []).length === 0 && "Nobody yet."}>
        <div className="scroll">
          <table>
            <thead>
              <tr><th>Name</th><th>Email</th><th>Role</th><th>Profiles</th><th /></tr>
            </thead>
            <tbody>
              {(users.data || []).map((person) => (
                <tr key={person.id} style={person.is_active ? undefined : { opacity: 0.55 }}>
                  <td className="strong">{person.name}</td>
                  <td className="muted mono small">{person.email}</td>
                  <td>
                    <Chip kind={person.role === "manager" ? "own" : ""}>
                      {person.role === "manager" ? "Manager" : "BD"}
                    </Chip>
                    {!person.is_active && <> <Chip kind="off">off</Chip></>}
                  </td>
                  <td className="muted small">{person.profiles.join(", ") || "—"}</td>
                  <td className="acts">
                    <button className="btn sm" onClick={() => act(
                      () => api.editUser(person.id, { is_active: !person.is_active }),
                      person.is_active ? `${person.name} can no longer sign in.`
                        : `${person.name} can sign in again.`
                    )}>{person.is_active ? "Switch off" : "Switch on"}</button>
                    {" "}
                    <Danger onConfirm={() => act(
                      () => api.removeUser(person.id),
                      `${person.name} deleted. Their profiles are free to reassign.`
                    )}>Delete</Danger>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </State>
    </div>
  );
}

/* ── Profiles ─────────────────────────────────────────────────────────── */

const NEW_PROFILE = { name: "", headline: "", platform: "", skills: "", user_id: "" };

function Identities({ profiles, users, onChange }) {
  const [form, setForm] = useState(NEW_PROFILE);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const bds = users.filter((u) => u.role === "bd" && u.is_active);

  async function add(event) {
    event.preventDefault();
    setBusy(true);
    try {
      const made = await api.addProfile({
        ...form,
        name: form.name.trim(),
        user_id: form.user_id ? Number(form.user_id) : null,
      });
      // The number matters: a new identity does not start empty, it starts
      // with whatever the rest of the team has already found.
      toast(made.handed_over
        ? `${made.name} added, and handed ${made.handed_over} job${made.handed_over === 1 ? "" : "s"} the team already found.`
        : `${made.name} added.`);
      setForm(NEW_PROFILE);
      onChange();
    } catch (e) {
      toast(e.message, "bad");
    } finally {
      setBusy(false);
    }
  }

  async function act(run, said) {
    try {
      await run();
      toast(said);
      onChange();
    } catch (e) {
      toast(e.message, "bad");
    }
  }

  return (
    <div className="card">
      <header>
        <h2>Add SSN Profile</h2>
        <span className="muted small">To Assign BD and Developer</span>
      </header>

      <form onSubmit={add} style={{ marginBottom: "var(--s5)" }}>
        <div className="grid">
          <Field label="Profile name" value={form.name} onChange={set("name")}
                 placeholder="Khuram — AI Engineer" required />
          <Field label="Headline" value={form.headline} onChange={set("headline")}
                 placeholder="AI / LLM Engineer" />
          <Field label="Where" value={form.platform} onChange={set("platform")}
                 placeholder="Upwork" />
          <Field label="Skills" value={form.skills} onChange={set("skills")}
                 placeholder="python, rag, llm" />
          <div className="field">
            <label>Assign to</label>
            <select value={form.user_id} onChange={set("user_id")}>
              <option value="">nobody yet</option>
              {bds.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select>
          </div>
        </div>
        <div className="row" style={{ marginTop: "var(--s3)" }}>
          <span className="spacer" />
          <button className="btn primary" disabled={busy}>{busy ? "Adding…" : "Add profile"}</button>
        </div>
      </form>

      <State busy={profiles.first} error={profiles.error}
             empty={(profiles.data || []).length === 0 && "No profiles yet."}>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Profile</th><th>Where</th><th>Assigned to</th>
                <th className="num">Own</th><th className="num">Others&apos;</th>
                <th className="num">Skipped</th><th className="num">Pending</th><th />
              </tr>
            </thead>
            <tbody>
              {(profiles.data || []).map((p) => (
                <tr key={p.id} style={p.is_active ? undefined : { opacity: 0.55 }}>
                  <td>
                    <span className="strong">{p.name}</span>
                    {!p.is_active && <> <Chip kind="off">off</Chip></>}
                    {p.headline && <span className="muted small"><br />{p.headline}</span>}
                  </td>
                  <td className="muted">{p.platform || "—"}</td>
                  <td>
                    {/* Reassigning is the same control as assigning. A profile
                        moving between BDs takes its whole history with it. */}
                    <select value={p.user_id || ""} onChange={(e) => act(
                      () => api.editProfile(p.id, {
                        user_id: e.target.value ? Number(e.target.value) : null,
                      }),
                      e.target.value ? "Reassigned." : "Taken off whoever held it."
                    )}>
                      <option value="">nobody</option>
                      {bds.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
                    </select>
                  </td>
                  <td className="num">{p.counts?.own ?? 0}</td>
                  <td className="num">{p.counts?.from_others ?? 0}</td>
                  <td className="num">{p.counts?.skipped ?? 0}</td>
                  <td className="num">{p.counts?.pending ?? 0}</td>
                  <td className="acts">
                    <button className="btn sm" onClick={() => act(
                      () => api.editProfile(p.id, { is_active: !p.is_active }),
                      p.is_active
                        ? "Switched off. What it never worked has gone back."
                        : "Switched on, and caught up on the pool."
                    )}>{p.is_active ? "Switch off" : "Switch on"}</button>
                    {" "}
                    <Danger title="Deletes this profile and its record. Permanent."
                            onConfirm={() => act(
                              () => api.removeProfile(p.id),
                              `${p.name} deleted. The jobs it found stay in the pool.`
                            )}>Delete</Danger>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </State>
    </div>
  );
}
