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
 *
 * Before anything is filed the lines are checked against every job this BD
 * has applied for, under any of their profiles. A match is not filed: the
 * line gets a warning saying where and when they applied, with **Ignore**
 * (file it anyway — a deliberate reapplication) and **Don't add**. The link
 * is checked as soon as it is typed, too, so the warning comes before the
 * rest of the line has been filled in.
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
// `uid` identifies a line across edits, pastes and removals, so a warning stays
// attached to the line it is about. `reapply` is set by Ignore.
let nextUid = 1;
const blank = (email = "") => ({ uid: nextUid++, company: "", title: "", url: "",
                                 platform: "", email, date: today(), reapply: false });
const toJob = (row) => ({
  company: row.company, title: row.title, url: row.url, platform: row.platform,
  email: row.email, applied_on: row.date, reapply: !!row.reapply,
});

/** "applied on 2026-09-20 under Khuram — AI Engineer (this profile)". */
const where = (hit) => `${hit.applied_on} under ${hit.profile}`
  + (hit.this_profile ? " (this profile)" : "");

export default function EntryGrid({ profile, onSaved }) {
  // The boards the manager keeps. Loaded rather than hard-coded, so adding one
  // is a thing somebody does on the People screen, not a release.
  const platforms = useLoad(() => api.platforms(), []);
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(false);
  // uid -> the earlier applications that line matches. A line with an entry
  // here is not filed until the BD presses Ignore or takes it out.
  const [warnings, setWarnings] = useState({});
  // Whether the warnings on screen stopped a Save. Only then does clearing the
  // last one finish that Save; a warning raised while typing the link waits
  // for the BD to finish the line.
  const saveWaiting = useRef(false);
  // The address the last line went out from, carried into the next one: people
  // apply from one inbox all morning, and retyping it every line is the kind of
  // friction that ends with the column left empty.
  const lastEmail = useRef("");
  const focusOn = useRef(null);
  const toast = useToast();

  // A profile switch must not carry the half-typed line for the last one over.
  useEffect(() => { setRows([]); setWarnings({}); }, [profile.id]);

  useEffect(() => {
    if (!focusOn.current) return;
    document.getElementById(focusOn.current)?.focus();
    focusOn.current = null;
  });

  const edit = (index, key, value) => setRows((current) => {
    const next = [...current];
    // Changing what identifies the line makes it a different job, so an
    // earlier Ignore no longer covers it and an old warning no longer fits.
    const changesJob = IDENTIFYING.includes(key);
    next[index] = { ...next[index], [key]: value,
                    ...(changesJob ? { reapply: false } : {}) };
    if (changesJob) forget(next[index].uid);
    if (key === "email") lastEmail.current = value;
    return next;
  });

  const forget = (uid) => setWarnings((current) => {
    if (!(uid in current)) return current;
    const next = { ...current };
    delete next[uid];
    return next;
  });

  const filled = rows.filter((row) => !isEmpty(row));
  const waiting = Object.keys(warnings).length;

  /** Ask the server which of `lines` this BD has already applied for.
   *  Returns {uid: applied[]} for the ones not already Ignored. */
  async function findRepeats(lines) {
    const asking = lines.filter((row) => !row.reapply);
    if (!asking.length) return {};
    const reply = await api.checkOwn(profile.id, asking.map(toJob));
    const found = {};
    for (const match of reply.matches) found[asking[match.index].uid] = match.applied;
    return found;
  }

  /** The link was just typed: warn now rather than at Save. Never blocks. */
  async function checkLine(row) {
    if (isEmpty(row) || row.reapply) return;
    try {
      const found = await findRepeats([row]);
      setWarnings((current) => {
        const next = { ...current };
        if (found[row.uid]) next[row.uid] = found[row.uid];
        else delete next[row.uid];
        return next;
      });
    } catch {
      /* a failed check is not a reason to stop typing; Save checks again */
    }
  }

  /** File what is filled in. Returns whether anything went.
   *
   *  `lines` is passed when the caller has just changed the rows (Ignore,
   *  Don't add) and state has not caught up yet. */
  async function commit(lines = rows) {
    const toFile = lines.filter((row) => !isEmpty(row));
    if (!toFile.length) return false;
    setBusy(true);
    try {
      const found = await findRepeats(toFile);
      if (Object.keys(found).length) {
        setWarnings(found);
        saveWaiting.current = true;
        const n = Object.keys(found).length;
        toast(`${n} ${n === 1 ? "line was" : "lines were"} applied for before. `
          + "Ignore to add anyway, or take the line out.", "bad");
        return false;
      }
      setWarnings({});
      saveWaiting.current = false;
      const tally = await api.logOwn(profile.id, toFile.map(toJob));
      // Every outcome, not just the happy one: a block of thirty where two
      // were already on record is exactly the case that needs saying out loud.
      const said = [
        tally.added && `${tally.added} new`,
        tally.known && `${tally.known} already in the pool`,
        tally.reapplied && `${tally.reapplied} reapplied`,
        tally.duplicate && `${tally.duplicate} you had already applied for`,
        tally.unusable && `${tally.unusable} with nothing to identify them`,
      ].filter(Boolean).join(", ");
      toast(said || "Nothing to file.",
            tally.added || tally.known || tally.reapplied ? "ok" : "bad");
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

  /** Ignore: file this line anyway. The last warning cleared files the lot. */
  function ignore(uid) {
    const next = rows.map((row) => (row.uid === uid ? { ...row, reapply: true } : row));
    setRows(next);
    forget(uid);
    if (waiting === 1 && saveWaiting.current) commit(next);
  }

  /** Don't add: take the line out. The last warning cleared files the rest. */
  function dontAdd(uid) {
    const next = rows.filter((row) => row.uid !== uid);
    setRows(next);
    forget(uid);
    if (waiting === 1 && saveWaiting.current && next.some((row) => !isEmpty(row))) {
      commit(next);
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
        else {
          // Pasted over, it is a different job: any Ignore or warning is stale.
          next[target] = { ...next[target], reapply: false };
          forget(next[target].uid);
        }
        cells.forEach((cell, across) => {
          const column = COLUMNS[start + across];
          if (column) next[target][column.key] = cell.trim();
        });
      });
      return next;
    });
  }

  const removeRow = (index) => {
    forget(rows[index]?.uid);
    setRows((current) => current.filter((_, i) => i !== index));
  };

  return (
    <div style={{ marginBottom: "var(--s5)" }}>
      <div className="row" style={{ marginBottom: "var(--s3)" }}>
        <h2>Log a job {profile.name} found</h2>
        <span className="spacer" />
        {filled.length > 0 && (
          <button className="link" disabled={busy} onClick={() => commit()}>Save now</button>
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
                  <React.Fragment key={row.uid}>
                  <tr className={warnings[row.uid] ? "warned" : undefined}>
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
                                 onBlur={column.key === "url" ? () => checkLine(row) : undefined}
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
                  {warnings[row.uid] && (
                    <tr className="repeat">
                      <td />
                      <td colSpan={COLUMNS.length + 1}>
                        <div className="row" style={{ gap: "var(--s2)", flexWrap: "wrap" }}>
                          <span>
                            <b>You already applied for this job</b> —{" "}
                            {warnings[row.uid].map(where).join("; ")}.
                          </span>
                          <span className="spacer" />
                          <button className="btn sm" disabled={busy}
                                  title="Add it anyway — you are reapplying on purpose"
                                  onClick={() => ignore(row.uid)}>Ignore</button>
                          <button className="btn sm" disabled={busy}
                                  onClick={() => dontAdd(row.uid)}>Don&apos;t add</button>
                        </div>
                      </td>
                    </tr>
                  )}
                  {row.reapply && !warnings[row.uid] && (
                    <tr className="repeat ignored">
                      <td />
                      <td colSpan={COLUMNS.length + 1} className="muted small">
                        Applied for before — will be added anyway.
                      </td>
                    </tr>
                  )}
                  </React.Fragment>
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
