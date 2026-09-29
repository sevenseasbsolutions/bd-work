/* All jobs, for the manager: one row per posting, nobody's standing on it.
 *
 * The same pool the BDs work, read from above — who found each job and how
 * many identities have gone in on it.
 */
import React, { useMemo, useState } from "react";
import { api } from "../api.js";
import { TODAY, asRow, CopyButton, DateRange, Empty, ExportButton, jobMatches,
         State, Tile, UrlCell, useLoad } from "./ui.jsx";

/* A copied row starts with the entry grid's own columns, so a manager pulling
   the pool into a sheet gets the same shape the BDs type into. Email and date
   are a profile's own and belong to nobody here, so the row carries when the
   posting was first seen instead. */
const COPY_HEADER = ["Company name", "Job title", "Job link", "Job platform",
                     "Found by", "Applications", "Applied by", "First seen"];

const copyRow = (job) => asRow([
  job.company, job.title, job.url, job.platform,
  job.found_by, job.applications, job.applied_by.join(", "),
  (job.first_seen || "").slice(0, 10),
]);

export default function Pool() {
  const [range, setRange] = useState(TODAY);
  const rows = useLoad(() => api.pool(range), [range.since, range.until]);
  const [query, setQuery] = useState("");

  const jobs = rows.data || [];
  const shown = useMemo(() => jobs.filter((job) => jobMatches(job, query)),
                        [jobs, query]);

  if (rows.error && !rows.data) return <Empty>{rows.error}</Empty>;

  const applications = jobs.reduce((sum, job) => sum + job.applications, 0);
  // Jobs nobody has gone in on yet: the pool's backlog, and the number a
  // manager actually acts on.
  const untouched = jobs.filter((job) => job.applications === 0).length;

  return (
    <div className="card">
      <header>
        <h1>All jobs</h1>
        <span className="muted small">Every posting anybody has found.</span>
      </header>

      <div style={{ marginBottom: "var(--s5)" }}>
        <DateRange value={range} onChange={setRange}>
          <ExportButton label="Export everything"
                        run={() => api.exportWorkspace(range)} />
        </DateRange>
      </div>

      <div className="tiles" style={{ marginBottom: "var(--s5)" }}>
        <Tile value={jobs.length} label="postings" accent />
        <Tile value={applications} label="applications against them" />
        <Tile value={untouched} label="nobody has applied for" />
      </div>

      <div className="wrap-row" style={{ marginBottom: "var(--s4)" }}>
        <div style={{ maxWidth: 280, width: "100%", flex: "0 1 280px" }}>
          <input type="text" value={query} onChange={(e) => setQuery(e.target.value)}
                 placeholder="Search job, client, finder or link" />
        </div>
        <span className="row" style={{ gap: "var(--s2)", marginLeft: "auto" }}>
          <span className="muted small">{shown.length} of {jobs.length}</span>
          <CopyButton label={`Copy ${shown.length === 1 ? "row" : "all " + shown.length}`}
                      title="Copy every row shown, with a header line, for Excel"
                      text={() => [asRow(COPY_HEADER), ...shown.map(copyRow)].join("\n")} />
        </span>
      </div>

      <State busy={rows.first} error={rows.error}
             empty={shown.length === 0 && (jobs.length ? "No jobs match that."
               : "The pool is empty. It fills as BDs log what they find.")}>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Company</th><th>Job title</th><th>Job link</th><th>Platform</th>
                <th>Found by</th>
                <th className="num">Applications</th><th>Applied by</th>
                <th>First seen</th><th className="acts" />
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
                  <td className="muted mono small nowrap">{(job.first_seen || "").slice(0, 10)}</td>
                  <td className="acts"><CopyButton text={() => copyRow(job)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </State>
    </div>
  );
}
