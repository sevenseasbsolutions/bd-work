/* Logging what a profile found, a line at a time.
 *
 * The same shape as the big app's entry table, cut to what MBS needs. Press
 * **+ New entry**, a line appears, you fill it in; pressing it again files that
 * line and starts the next. Nothing reaches the server until you do.
 *
 * Column order is the order the work actually happens in — you have the client
 * and the role first, the link second, and the last two are filled in for you:
 *
 *     Company name · Job title · Job link · Job platform · Email · Date
 */
import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { today, useLoad, useToast } from "./ui.jsx";

export const COLUMNS = [
  { key: "company", label: "Company name", hint: "Northwind Labs", width: "16%" },
  { key: "title", label: "Job title", hint: "Senior RAG Engineer", width: "19%" },
  { key: "url", label: "Job link", hint: "https://…", width: "22%" },
  { key: "platform", label: "Job platform", hint: "", width: "13%" },
  { key: "email", label: "Email", hint: "applied from…", width: "18%" },
  { key: "date", label: "Date", hint: "", width: "12%" },
];

// What makes a line a job: a client, a title, or a link. The date and the
// email do not count — both are filled in for you, so counting them would
// file an untouched line as work.
const IDENTIFYING = ["company", "title", "url"];
const isEmpty = (row) => IDENTIFYING.every((key) => !String(row[key] || "").trim());
const blank = (email = "") => ({ company: "", title: "", url: "", platform: "",
                                 email, date: today() });

export default function EntryGrid({ profile, onSaved }) {
  // The boards the manager keeps. Loaded rather than hard-coded, so adding one
  // is a thing somebody does on the People screen, not a release.
  const platforms = useLoad(() => api.platforms(), []);
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(false);
  // The address the last line went out from, carried into the next one: people
  // apply from one inbox all morning, and retyping it every line is the kind of
  // friction that ends with the column left empty.
  const lastEmail = useRef("");
  const focusOn = useRef(null);
  const toast = useToast();

  // A profile switch must not carry the half-typed line for the last one over.
  useEffect(() => { setRows([]); }, [profile.id]);

  useEffect(() => {
    if (!focusOn.current) return;
    document.getElementById(focusOn.current)?.focus();
    focusOn.current = null;
  });

  const edit = (index, key, value) => setRows((current) => {
    const next = [...current];
    next[index] = { ...next[index], [key]: value };
    if (key === "email") lastEmail.current = value;
    return next;
  });

  const filled = rows.filter((row) => !isEmpty(row));

  /** File what is filled in. Returns whether anything went. */
  async function commit() {
    if (!filled.length) return false;
    setBusy(true);
    try {
      const tally = await api.logOwn(profile.id, filled.map((row) => ({
        company: row.company, title: row.title, url: row.url,
        platform: row.platform, email: row.email, applied_on: row.date,
      })));
      // All four outcomes, not just the happy one: a block of thirty where two
      // were already on record is exactly the case that needs saying out loud.
      const said = [
        tally.added && `${tally.added} new`,
        tally.known && `${tally.known} already in the pool`,
        tally.duplicate && `${tally.duplicate} you had already applied for`,
        tally.unusable && `${tally.unusable} with nothing to identify them`,
      ].filter(Boolean).join(", ");
      toast(said || "Nothing to file.", tally.added || tally.known ? "ok" : "bad");
      setRows([]);
      onSaved();
      return true;
    } catch (e) {
      toast(e.message, "bad");
      return false;
    } finally {
      setBusy(false);
    }
  }

  /** + New entry: file whatever is filled in, then open a fresh line. */
  async function addRow() {
    if (filled.length) {
      const went = await commit();
      if (!went) return;          // it failed — leave the typing where it is
      focusOn.current = "cell-0-company";
      setRows([blank(lastEmail.current)]);
      return;
    }
    setRows((current) => {
      focusOn.current = `cell-${current.length}-company`;
      return [...current, blank(lastEmail.current)];
    });
  }

  /** A block pasted out of Excel fills across and down from the cell it lands
   *  in, growing the grid as it goes. This is the other half of the Copy
   *  button on All jobs: what comes out pastes back in. */
  function onPaste(index, key, event) {
    const text = event.clipboardData.getData("text/plain");
    if (!text || (!text.includes("\t") && !text.includes("\n"))) return;
    event.preventDefault();

    const grid = text.replace(/\r/g, "").split("\n").filter((line) => line !== "")
      .map((line) => line.split("\t"));
    const start = COLUMNS.findIndex((column) => column.key === key);

    setRows((current) => {
      const next = [...current];
      grid.forEach((cells, down) => {
        const target = index + down;
        if (!next[target]) next[target] = blank(lastEmail.current);
        else next[target] = { ...next[target] };
        cells.forEach((cell, across) => {
          const column = COLUMNS[start + across];
          if (column) next[target][column.key] = cell.trim();
        });
      });
      return next;
    });
  }

  const removeRow = (index) => setRows((current) => current.filter((_, i) => i !== index));

  return (
    <div style={{ marginBottom: "var(--s5)" }}>
      <div className="row" style={{ marginBottom: "var(--s3)" }}>
        <h2>Log a job {profile.name} found</h2>
        <span className="spacer" />
        {filled.length > 0 && (
          <button className="link" disabled={busy} onClick={commit}>Save now</button>
        )}
        <button className="btn primary" disabled={busy} onClick={addRow}>
          {busy ? "Saving…" : "+ New entry"}
        </button>
      </div>

      {rows.length === 0 ? (
        <p className="muted small" style={{ margin: 0 }}>
          Press <b>+ New entry</b> to add a line. The date is stamped for you, and
          a block pasted from Excel fills across.
        </p>
      ) : (
        <>
          <div className="scroll">
            <table className="entry">
              <thead>
                <tr>
                  <th style={{ width: 28 }}>#</th>
                  {COLUMNS.map((column) => (
                    <th key={column.key} style={{ width: column.width }}>{column.label}</th>
                  ))}
                  <th style={{ width: 28 }} aria-label="Remove" />
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={index}>
                    <td className="mono muted num">{index + 1}</td>
                    {COLUMNS.map((column) => (
                      <td key={column.key} style={{ padding: 3 }}>
                        {column.key === "platform" ? (
                          <select id={`cell-${index}-${column.key}`} className="cell"
                                  value={row.platform}
                                  onChange={(e) => edit(index, "platform", e.target.value)}>
                            <option value="">— where —</option>
                            {(platforms.data || []).map((option) => (
                              <option key={option.id} value={option.name}>{option.name}</option>
                            ))}
                            {/* A row pasted from a sheet, or filed before the
                                manager retired that board, still shows what it
                                actually says rather than falling back to blank. */}
                            {row.platform
                              && !(platforms.data || []).some((o) => o.name === row.platform) && (
                              <option value={row.platform}>{row.platform}</option>
                            )}
                          </select>
                        ) : (
                          <input id={`cell-${index}-${column.key}`} className="cell"
                                 type="text" value={row[column.key] || ""}
                                 placeholder={column.hint}
                                 title={column.key === "date"
                                   ? "Stamped for you. Edit it if you are backfilling."
                                   : undefined}
                                 style={column.key === "date"
                                   ? { fontFamily: "var(--mono)", fontSize: 12 } : undefined}
                                 onChange={(e) => edit(index, column.key, e.target.value)}
                                 onPaste={(e) => onPaste(index, column.key, e)}
                                 onKeyDown={(e) => {
                                   // Enter on the last line files it and opens
                                   // the next, so a run of entries never needs
                                   // the mouse.
                                   if (e.key === "Enter" && index === rows.length - 1) {
                                     e.preventDefault();
                                     addRow();
                                   }
                                 }} />
                        )}
                      </td>
                    ))}
                    <td style={{ textAlign: "center", padding: 3 }}>
                      <button className="link" title="Drop this line. It has not been filed."
                              onClick={() => removeRow(index)}>×</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="row" style={{ marginTop: "var(--s2)" }}>
            <span className="muted small">
              {filled.length
                ? <><b>{filled.length}</b> {filled.length === 1 ? "line" : "lines"} not filed yet — press <b>+ New entry</b> or <b>Save now</b>.</>
                : "A line counts once it has a client, a title or a link."}
            </span>
            <span className="spacer" />
            <span className="muted small">
              The link is what makes it the same job as everybody else&apos;s copy.
            </span>
          </div>
        </>
      )}
    </div>
  );
}
