/* Three months of somebody's spreadsheet, into the pool.
 *
 * It sits above the entry grid because it is the same act as the grid — a job
 * this profile found and applied for — done three thousand at a time. Folded
 * away by default: a BD logging today's work should not have to look past a
 * migration tool every morning.
 *
 * The report afterwards is the reason this screen exists at all. Six numbers
 * that add up to the number of lines in the file, so "2,750 of my 3,000 went
 * in" is followed by where the other 250 are rather than by a shrug — and a
 * button that hands the unfiled ones back as a sheet to fix and send again.
 */
import React, { useRef, useState } from "react";
import { api } from "../api.js";
import { ExportButton, State, useLoad, useToast } from "./ui.jsx";

const ACCEPT = ".xlsx,.xlsm,.csv,.tsv";

/* The six buckets every line lands in, in the order they are worth reading:
   what went in, what was already there, and what did not go in. `tone` is
   what the number means, not how big it is — 250 unread lines is a warning at
   any size, and 250 duplicates is not. */
const BUCKETS = [
  ["added", "new postings added", "ok",
   "New to the pool. Everybody else has them on their others' jobs list now."],
  ["known", "already in the pool", "",
   "A colleague had already found these. This profile now counts among the applicants."],
  ["duplicate", "already on this profile", "",
   "On record before the upload. Left exactly as they were."],
  ["repeated", "repeated within the sheet", "",
   "The same posting on more than one line of the file. Counted once."],
  ["clashing", "one link, two companies", "warn",
   "The same job link as an earlier line, under a different company. One of the two links is probably on the wrong line — download them, fix the link, upload again."],
  /* Only ever non-zero on an upload from before every line counted as
     applied; hidden otherwise. */
  ["not_applied", "marked not applied for", "warn",
   "An older upload held these back on its Status column."],
  ["unusable", "could not be read", "warn",
   "No link, no company and no job title — nothing to identify a posting by."],
];

const day = (iso) => (iso ? iso.slice(0, 10) : "");
const when = (iso) => (iso ? iso.slice(0, 16).replace("T", " ") : "");

export default function SheetImport({ profile, onFiled }) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  const past = useLoad(() => api.imports(profile.id), [profile.id]);
  const box = useRef(null);
  const toast = useToast();

  /* A profile switch must not carry the last one's file or report across —
     uploading Ayesha's sheet against Bilal is not an undoable mistake. */
  const [seen, setSeen] = useState(profile.id);
  if (seen !== profile.id) {
    setSeen(profile.id);
    setFile(null);
    setReport(null);
  }

  function take(chosen) {
    if (!chosen) return;
    setFile(chosen);
    setReport(null);
  }

  async function send() {
    if (!file || busy) return;
    setBusy(true);
    try {
      const done = await api.importSheet(profile.id, file);
      setReport(done);
      setFile(null);
      if (box.current) box.current.value = "";
      const landed = done.added + done.known;
      toast(landed
        ? `${landed} line${landed === 1 ? "" : "s"} filed from ${done.filename}.`
        : "Nothing new in that sheet — every line was already on record.",
      landed || done.duplicate ? "ok" : "bad");
      past.reload();
      onFiled();
    } catch (e) {
      toast(e.message, "bad");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div className="row" style={{ marginBottom: "var(--s4)" }}>
        <span className="muted small">
          Been keeping this in a spreadsheet? Bring it across — nothing is lost
          and uploading twice is safe.
        </span>
        <span className="spacer" />
        <button className="btn sm" onClick={() => setOpen(true)}>Import a sheet</button>
      </div>
    );
  }

  return (
    <div className="importer">
      <div className="row" style={{ marginBottom: "var(--s3)" }}>
        <h2 style={{ margin: 0 }}>Import an old sheet</h2>
        <span className="spacer" />
        <ExportButton small label="Download template" run={api.exportTemplate}
                      title="An empty sheet with the six columns, and a page explaining them" />
        <button className="link" onClick={() => setOpen(false)}>Close</button>
      </div>

      <p className="muted small" style={{ marginTop: 0 }}>
        Every line becomes a job <b>{profile.name}</b> found and applied for —
        it shows on Own jobs and on All jobs, and lands on every other live
        profile&apos;s others&apos; jobs list, exactly as if it had been typed into
        the grid below. Any Status column is ignored: every line is marked
        applied. The columns can be in any order and the header row does not
        have to be the first row. A tab from the team&apos;s Google Sheet uploads
        as it is; a whole downloaded workbook reads only
        the <b>{profile.name}</b> tab.
      </p>

      <label className={`drop ${over ? "over" : ""}`}
             onDragOver={(e) => { e.preventDefault(); setOver(true); }}
             onDragLeave={() => setOver(false)}
             onDrop={(e) => {
               e.preventDefault();
               setOver(false);
               take(e.dataTransfer.files?.[0]);
             }}>
        <input ref={box} type="file" accept={ACCEPT} disabled={busy}
               onChange={(e) => take(e.target.files?.[0])} />
        <span>
          {file
            ? <><b>{file.name}</b> <span className="muted small">
                — {(file.size / 1024).toFixed(0)} KB</span></>
            : <>Drop an <b>.xlsx</b> or <b>.csv</b> here, or choose one.</>}
        </span>
      </label>

      <div className="row" style={{ marginTop: "var(--s3)" }}>
        <span className="muted small">
          Applied on · Company name · Job title · Job link · Job platform · Email
          — the Google Sheet&apos;s columns. Client, Role, Link, Portal and Date
          are understood too.
        </span>
        <span className="spacer" />
        <button className="btn primary" disabled={!file || busy} onClick={send}>
          {busy ? "Filing…" : "Upload"}
        </button>
      </div>

      {busy && (
        <p className="muted small" style={{ marginBottom: 0 }}>
          A long sheet takes a while. It is filed in batches as it goes, so
          nothing is lost if this is interrupted — upload the same file again
          and only what is missing is added.
        </p>
      )}

      {report && <Report report={report} />}

      <History rows={past} />
    </div>
  );
}

/* ── What became of the file ──────────────────────────────────────────── */

function Report({ report }) {
  const filed = report.added + report.known;
  const left = report.left_over;

  return (
    <div className="report">
      <div className="row" style={{ marginBottom: "var(--s3)" }}>
        <b>{filed} of {report.rows}</b>
        <span className="muted small">
          line{report.rows === 1 ? "" : "s"} in {report.filename}
          {report.sheets ? ` · ${report.sheets}` : ""} went into the pool.
        </span>
        <span className="spacer" />
        {left > 0 && (
          <ExportButton small label={`Download the ${left} left over`}
                        title="The lines that did not go in, in a sheet that imports back"
                        run={() => api.exportLeftovers(report.id)} />
        )}
      </div>

      {report.same_file_as && (
        <p className="muted small" style={{ marginTop: 0 }}>
          This is the same file you uploaded on {day(report.same_file_as)}.
          Nothing was doubled — anything already on record was counted and left
          alone.
        </p>
      )}

      <div className="buckets">
        {BUCKETS.filter(([key]) => key !== "not_applied" || report[key])
          .map(([key, label, tone, why]) => (
          <div key={key} className={`bucket ${report[key] ? tone : "nil"}`} title={why}>
            <b>{report[key]}</b><span>{label}</span>
          </div>
        ))}
      </div>

      <p className="muted small" style={{ marginBottom: 0 }}>
        {/* The invariant, said out loud. It is the whole reason to trust the
            number above it. */}
        Those add up to the {report.rows} line{report.rows === 1 ? "" : "s"} read
        out of the file — every one is accounted for.
        {left > 0 && " Fix the ones left over and upload that file; only what is missing is added."}
      </p>

      {report.undated > 0 && (
        <p className="muted small" style={{ marginBottom: 0 }}>
          <b>{report.undated}</b> line{report.undated === 1 ? " was" : "s were"} filed
          with no date that could be read, so {report.undated === 1 ? "it counts" : "they count"} against
          today. Fix the date column and upload the same file again to put them on
          the right day — nothing is doubled.
        </p>
      )}
    </div>
  );
}

/* ── Every sheet ever brought across ──────────────────────────────────── */

function History({ rows }) {
  const list = rows.data || [];

  return (
    <div style={{ marginTop: "var(--s5)" }}>
      <h3 className="muted small" style={{ margin: "0 0 var(--s2)" }}>
        Sheets brought across
      </h3>
      <State busy={rows.first} error={rows.error}
             empty={list.length === 0 && "No sheet has been uploaded against this profile."}>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>File</th><th>When</th><th>By</th>
                <th className="num">Lines</th><th className="num">Added</th>
                <th className="num">Already there</th><th className="num">Left over</th>
                <th className="acts" />
              </tr>
            </thead>
            <tbody>
              {list.map((row) => (
                <tr key={row.id}>
                  <td className="strong">{row.filename}</td>
                  <td className="muted small mono nowrap">{when(row.at)}</td>
                  <td className="muted small">{row.by || "—"}</td>
                  <td className="num">{row.rows}</td>
                  <td className="num">{row.added}</td>
                  <td className="num">{row.known + row.duplicate + row.repeated}</td>
                  <td className="num">{row.left_over || "—"}</td>
                  <td className="acts">
                    {row.left_over > 0 && (
                      <ExportButton small label="Left over"
                                    title="The lines this upload could not file"
                                    run={() => api.exportLeftovers(row.id)} />
                    )}
                    {!row.finished && (
                      <span className="chip pending" title={
                        "This upload did not finish. What it reached is filed — "
                        + "upload the same file again to add the rest."
                      }>cut short</span>
                    )}
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
