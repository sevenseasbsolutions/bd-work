/* The BD's whole application: pick a profile, work its three lists.
 *
 * Own jobs      what this profile went out and found
 * Others' jobs  what somebody else found, handed to this profile to apply for
 * All jobs      the pool, with this profile's standing on every row
 *
 * The date range at the top governs all three at once, and the tiles with
 * them. It lives here rather than inside a tab so that switching tab does not
 * silently change the window somebody is reading.
 *
 * A manager lands here too, reading somebody else's profile. Everything that
 * writes is hidden for them: the numbers are theirs to check, the work is not
 * theirs to do.
 */
import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import EntryGrid from "./EntryGrid.jsx";
import SheetImport from "./SheetImport.jsx";
import { ALL_TIME, asRow, Chip, CopyButton, Danger, DateRange, Empty, ExportButton,
         jobMatches, State, Tile, UrlCell, useLoad, useToast } from "./ui.jsx";

const STANDING = {
  own: "Own job", applied: "Applied", skipped: "Skipped",
  pending: "Pending", none: "—",
};

const day = (iso) => (iso ? iso.slice(0, 10) : "");

/** An empty list has two quite different meanings, and saying the wrong one
 *  sends somebody looking for a bug. "Nothing pending" is only true when the
 *  window is the whole history; inside a range it is "nothing in these days". */
const emptyBecause = (range, inRange, always) =>
  (range.since || range.until) ? inRange : always;

export default function BdWork({ readOnly = false }) {
  const [range, setRange] = useState(ALL_TIME);
  const profiles = useLoad(() => api.profiles(range), [range.since, range.until]);
  // The manager's switches. Read once for the screen rather than per tab, and
  // read at all because a BD screen has to know what it is allowed to draw.
  const switches = useLoad(() => api.settings(), []);
  const [pickedId, setPicked] = useState(null);
  const [tab, setTab] = useState("own");

  const list = profiles.data || [];
  // Pick the first profile as soon as one exists, and let go of one that has
  // just been deleted rather than asking the server for it forever.
  useEffect(() => {
    if (!list.length) return;
    if (!list.some((p) => p.id === pickedId)) setPicked(list[0].id);
  }, [list, pickedId]);

  const picked = list.find((p) => p.id === pickedId) || null;
  const counts = picked?.counts || {};

  if (profiles.error && !profiles.data) return <Empty>{profiles.error}</Empty>;
  // `first`, not `busy`: a refresh must not swap the screen for a spinner and
  // take a half-typed entry line down with it.
  if (profiles.first) return <Empty>Loading…</Empty>;
  if (!list.length) {
    return (
      <Empty>
        No profiles yet.<br />
        <span className="small">A manager adds a profile and assigns it to you.</span>
      </Empty>
    );
  }

  return (
    <div className="split">
      <aside className="rail">
        <h3 className="muted" style={{ padding: "0 11px 4px" }}>
          {readOnly ? "Every profile" : "My profiles"}
        </h3>
        {list.map((p) => (
          <button key={p.id} className="pick" aria-current={p.id === pickedId}
                  onClick={() => setPicked(p.id)}>
            <span className="nm">{p.name}</span>
            <span className="sub">
              {p.headline || p.platform || "—"}
              {p.counts?.pending ? ` · ${p.counts.pending} pending` : ""}
            </span>
          </button>
        ))}
      </aside>

      <section>
        <div style={{ marginBottom: "var(--s4)" }}>
          <DateRange value={range} onChange={setRange}>
            {picked && (
              <ExportButton label={`Export ${picked.name.split(" — ")[0]}`}
                            run={() => api.exportProfile(picked.id, range)} />
            )}
          </DateRange>
        </div>

        <div className="card">
          <header>
            <h1>{picked?.name}</h1>
            <span className="muted small">
              {[picked?.headline, picked?.platform].filter(Boolean).join(" · ")}
            </span>
            <span className="spacer" />
            {!picked?.is_active && <Chip kind="off">Switched off</Chip>}
          </header>
          <div className="tiles">
            <Tile value={counts.own ?? 0} label="own jobs" accent />
            <Tile value={counts.pending ?? 0} label="others' jobs pending" />
            <Tile value={counts.from_others ?? 0} label="others' jobs applied for" />
            <Tile value={counts.skipped ?? 0} label="skipped" />
            <Tile value={counts.applied ?? 0} label="applied in all" />
          </div>
        </div>

        <div className="card">
          <div className="subtabs" role="tablist">
            {[
              ["own", "Own jobs", counts.own],
              ["others", "Others' jobs", counts.pending],
              ["all", "All jobs", null],
            ].map(([key, label, count]) => (
              <button key={key} className="subtab" role="tab" aria-current={tab === key}
                      onClick={() => setTab(key)}>
                {label}{count ? <span className="count">{count}</span> : null}
              </button>
            ))}
          </div>

          {picked && tab === "own" && (
            <OwnJobs profile={picked} range={range} readOnly={readOnly}
                     onChange={profiles.reload} />
          )}
          {picked && tab === "others" && (
            <OthersJobs profile={picked} range={range} readOnly={readOnly}
                        selectAll={switches.data?.select_all !== false}
                        onChange={profiles.reload} />
          )}
          {picked && tab === "all" && <AllJobs profile={picked} range={range} />}
        </div>
      </section>
    </div>
  );
}

/* ── Own jobs ─────────────────────────────────────────────────────────── */

function OwnJobs({ profile, range, readOnly, onChange }) {
  const rows = useLoad(() => api.own(profile.id, range),
                       [profile.id, range.since, range.until]);
  const toast = useToast();

  function filed() {
    rows.reload();
    onChange();
  }

  async function remove(applicationId) {
    try {
      const reply = await api.dropOwn(profile.id, applicationId);
      toast(reply.job_withdrawn
        ? "Taken off this profile, and withdrawn from everybody else's list."
        : "Taken off this profile. A colleague has applied, so the posting stays.");
      filed();
    } catch (e) {
      toast(e.message, "bad");
    }
  }

  return (
    <>
      {/* Above the grid because it is the same act done three thousand at a
          time, and because the first thing a team arriving from a spreadsheet
          needs is not a blank line to type into. */}
      {!readOnly && <SheetImport profile={profile} onFiled={filed} />}
      {!readOnly && <EntryGrid profile={profile} onSaved={filed} />}

      <State busy={rows.first} error={rows.error}
             empty={(rows.data || []).length === 0 && emptyBecause(range,
               "Nothing logged under this profile in these days.",
               "Nothing logged under this profile yet.")}>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Company</th><th>Job title</th><th>Job link</th><th>Platform</th>
                <th>Email</th><th>Date</th><th>Also applied</th>
                {!readOnly && <th className="acts" />}
              </tr>
            </thead>
            <tbody>
              {(rows.data || []).map((job) => (
                <tr key={job.application_id}>
                  <td className="strong">{job.company || "—"}</td>
                  <td>{job.title || "Untitled"}</td>
                  <td><UrlCell url={job.url} /></td>
                  <td className="muted">{job.platform || "—"}</td>
                  <td className="muted small">{job.email || "—"}</td>
                  <td className="muted small mono nowrap">
                    {job.applied_on || day(job.logged_at)}
                  </td>
                  <td className="muted small">
                    {job.also_applied.length ? job.also_applied.join(", ") : "—"}
                  </td>
                  {!readOnly && (
                    <td className="acts">
                      <Danger onConfirm={() => remove(job.application_id)}>Remove</Danger>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </State>
    </>
  );
}

/* ── Others' jobs ─────────────────────────────────────────────────────── */

function OthersJobs({ profile, range, readOnly, selectAll, onChange }) {
  const [status, setStatus] = useState("pending");
  const rows = useLoad(() => api.others(profile.id, status, range),
                       [profile.id, status, range.since, range.until]);
  // What is ticked, by assignment id. Held here rather than on each row so
  // that Select all is one change and not one per row.
  const [picked, setPicked] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const list = rows.data || [];
  const ticking = selectAll && !readOnly;

  // A tick only means anything while the row it is on is on screen. Changing
  // tab, profile or date range leaves that list behind, and a selection that
  // outlived its list is a press nobody can predict the result of.
  useEffect(() => { setPicked(new Set()); },
            [profile.id, status, range.since, range.until]);

  const shown = useMemo(() => new Set(list.map((job) => job.assignment_id)), [list]);
  const chosen = useMemo(() => [...picked].filter((id) => shown.has(id)), [picked, shown]);
  const all = list.length > 0 && chosen.length === list.length;

  const tick = (id) => setPicked((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });

  const tickAll = () => setPicked(all ? new Set() : new Set(shown));

  async function move(assignmentId, next) {
    try {
      await api.move(assignmentId, next);
      toast(next === "applied" ? "Marked as applied."
        : next === "skipped" ? "Turned down." : "Back on the list.");
      rows.reload();
      onChange();
    } catch (e) {
      toast(e.message, "bad");
    }
  }

  /** The same move, for everything ticked, in one request. */
  async function moveChosen(next) {
    if (!chosen.length || busy) return;
    setBusy(true);
    try {
      const done = await api.moveMany(chosen, next);
      const word = next === "applied" ? "marked as applied"
        : next === "skipped" ? "turned down" : "back on the list";
      toast(`${done.moved} ${done.moved === 1 ? "job" : "jobs"} ${word}.`
        + (done.unchanged ? ` ${done.unchanged} already ${done.unchanged === 1 ? "was" : "were"}.` : ""));
      setPicked(new Set());
      rows.reload();
      onChange();
    } catch (e) {
      toast(e.message, "bad");
    } finally {
      setBusy(false);
    }
  }

  const empty = emptyBecause(range,
    {
      pending: "Nothing pending in these days.",
      applied: "Nothing of anybody else's applied for in these days.",
      skipped: "Nothing turned down in these days.",
    }[status],
    {
      pending: "Nothing pending. Everything handed to this profile has been dealt with.",
      applied: "This profile has not applied for anybody else's find yet.",
      skipped: "Nothing turned down.",
    }[status]);

  return (
    <>
      <div className="wrap-row" style={{ marginBottom: "var(--s4)" }}>
        {/* The same three words the server uses for the status itself, so a
            row's state reads the same in the UI and in the API. */}
        {[["pending", "Pending jobs"], ["applied", "Applied"], ["skipped", "Skipped"]].map(
          ([key, label]) => (
            <button key={key} className={`btn sm ${status === key ? "primary" : ""}`}
                    onClick={() => setStatus(key)}>{label}</button>
          )
        )}
        <span className="spacer" />
        <span className="muted small">Found by other profiles and handed to this one.</span>
      </div>

      {/* The bar exists only while something is ticked. An empty one would be a
          row of buttons that do nothing, above every list, forever. */}
      {ticking && chosen.length > 0 && (
        <div className="bulk">
          <b>{chosen.length}</b>
          <span className="muted small">
            selected of the {list.length} shown
            {(range.since || range.until) ? " in this date range" : ""}
          </span>
          <span className="spacer" />
          {status === "pending" ? (
            <>
              <button className="btn sm ok" disabled={busy}
                      title="Mark every selected job as applied for"
                      onClick={() => moveChosen("applied")}>
                {busy ? "Working…" : `Applied · ${chosen.length}`}
              </button>
              <button className="btn sm" disabled={busy}
                      title="Turn down every selected job"
                      onClick={() => moveChosen("skipped")}>
                {busy ? "Working…" : `Skip · ${chosen.length}`}
              </button>
            </>
          ) : (
            <button className="btn sm" disabled={busy}
                    title="Put every selected job back on the pending list"
                    onClick={() => moveChosen("pending")}>
              {busy ? "Working…" : `Undo · ${chosen.length}`}
            </button>
          )}
          <button className="link" disabled={busy}
                  onClick={() => setPicked(new Set())}>Clear</button>
        </div>
      )}

      <State busy={rows.first} error={rows.error}
             empty={list.length === 0 && empty}>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                {ticking && (
                  <th className="tick">
                    {/* One box, and it is the whole of the feature: an imported
                        sheet can put three thousand rows on this list. */}
                    <input type="checkbox" checked={all} onChange={tickAll}
                           title={all ? "Clear the selection"
                             : `Select all ${list.length} shown`}
                           aria-label={`Select all ${list.length} shown`} />
                  </th>
                )}
                <th>Company</th><th>Job title</th><th>Job link</th><th>Platform</th>
                <th>Found by</th><th>Already applied</th>
                {!readOnly && <th className="acts" />}
              </tr>
            </thead>
            <tbody>
              {list.map((job) => (
                <tr key={job.assignment_id}
                    className={picked.has(job.assignment_id) ? "picked" : undefined}>
                  {ticking && (
                    <td className="tick">
                      <input type="checkbox" checked={picked.has(job.assignment_id)}
                             onChange={() => tick(job.assignment_id)}
                             aria-label={`Select ${job.title || "this job"}`} />
                    </td>
                  )}
                  <td className="strong">{job.company || "—"}</td>
                  <td>{job.title || "Untitled"}</td>
                  <td><UrlCell url={job.url} /></td>
                  <td className="muted">{job.platform || "—"}</td>
                  <td className="muted">{job.found_by || "—"}</td>
                  <td className="muted small">
                    {/* The reason this column exists: two colleagues already in
                        front of this client is worth knowing before writing a
                        cover letter, not after. */}
                    {job.applied_by.length ? job.applied_by.join(", ") : "nobody yet"}
                  </td>
                  {!readOnly && (
                    <td className="acts">
                      {status === "pending" ? (
                        <span className="row" style={{ justifyContent: "flex-end", gap: "var(--s2)" }}>
                          <button className="btn sm ok"
                                  onClick={() => move(job.assignment_id, "applied")}>Applied</button>
                          <button className="btn sm"
                                  onClick={() => move(job.assignment_id, "skipped")}>Skip</button>
                        </span>
                      ) : (
                        <button className="btn sm"
                                onClick={() => move(job.assignment_id, "pending")}>Undo</button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </State>
    </>
  );
}

/* ── All jobs ─────────────────────────────────────────────────────────── */

/* What a copied row holds, in the order the entry grid asks for it, so a row
   copied out of here pastes back into a sheet — or into the grid — as itself. */
const COPY_HEADER = ["Company name", "Job title", "Job link", "Job platform",
                     "Email", "Date", "Found by", "Applied by", "This profile"];

const copyRow = (job) => asRow([
  job.company, job.title, job.url, job.platform,
  job.my_email, job.my_date || day(job.first_seen),
  job.found_by, job.applied_by.join(", "), STANDING[job.standing],
]);

function AllJobs({ profile, range }) {
  const rows = useLoad(() => api.allJobs(profile.id, range),
                       [profile.id, range.since, range.until]);
  const [query, setQuery] = useState("");
  const [only, setOnly] = useState("all");

  const shown = useMemo(() => (rows.data || []).filter(
    (job) => (only === "all" || job.standing === only) && jobMatches(job, query)
  ), [rows.data, query, only]);

  return (
    <>
      <div className="wrap-row" style={{ marginBottom: "var(--s4)" }}>
        <div style={{ minWidth: 200, flex: "0 1 240px" }}>
          <input type="text" value={query} onChange={(e) => setQuery(e.target.value)}
                 placeholder="Search job, client, finder or link" />
        </div>
        {[["all", "Everything"], ["own", "Own"], ["applied", "Applied"],
          ["pending", "Pending"], ["skipped", "Skipped"], ["none", "Untouched"]].map(
          ([key, label]) => (
            <button key={key} className={`btn sm ${only === key ? "primary" : ""}`}
                    onClick={() => setOnly(key)}>{label}</button>
          )
        )}
        {/* Grouped, and pushed right with a margin rather than a flex spacer:
            in a row that wraps, a spacer sends the count and the button to a
            line of their own on the left, which reads as a mistake. */}
        <span className="row" style={{ gap: "var(--s2)", marginLeft: "auto" }}>
          <span className="muted small">{shown.length} of {(rows.data || []).length}</span>
          {/* Whatever is on screen — search, filter and date range included —
              as one block with a header line, for the person whose real report
              is a sheet. */}
          <CopyButton label={`Copy ${shown.length === 1 ? "row" : "all " + shown.length}`}
                      title="Copy every row shown, with a header line, for Excel"
                      text={() => [asRow(COPY_HEADER), ...shown.map(copyRow)].join("\n")} />
        </span>
      </div>

      <State busy={rows.first} error={rows.error}
             empty={shown.length === 0 && ((rows.data || []).length
               ? "No jobs match that."
               : emptyBecause(range, "No postings came in during these days.",
                              "The pool is empty. It fills as BDs log what they find."))}>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Company</th><th>Job title</th><th>Job link</th><th>Platform</th>
                <th>Found by</th><th className="num">Applications</th>
                <th>Applied by</th><th>This profile</th><th className="acts" />
              </tr>
            </thead>
            <tbody>
              {shown.map((job) => (
                <tr key={job.id}>
                  <td className="strong">{job.company || "—"}</td>
                  <td>{job.title || "Untitled"}</td>
                  <td><UrlCell url={job.url} /></td>
                  <td className="muted">{job.platform || "—"}</td>
                  <td className="muted">{job.found_by || "—"}</td>
                  <td className="num">{job.applications}</td>
                  <td className="muted small">
                    {job.applied_by.length ? job.applied_by.join(", ") : "—"}
                  </td>
                  <td><Chip kind={job.standing}>{STANDING[job.standing]}</Chip></td>
                  <td className="acts"><CopyButton text={() => copyRow(job)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </State>
    </>
  );
}
