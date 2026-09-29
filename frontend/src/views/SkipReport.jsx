/* What the Skipped tile opens onto: who turned down how much, and why.
 *
 * Three views of one set of rows, all read through the overview's date range:
 * a bar per BD split by reason, the same numbers as a pivot (BD down the side,
 * reason across the top), and the reasons people typed that are not one of
 * the suggestions — the "Other" column, spelled out.
 */
import React, { useState } from "react";
import { api } from "../api.js";
import { Empty, State, useLoad } from "./ui.jsx";

const pct = (rate) => `${Math.round(rate * 100)}%`;

/** Reason → its series colour. Fixed by position in the server's list, so a
 *  reason keeps its colour whichever BDs happen to be on screen. */
const hue = (reasons, reason) => `var(--series-${reasons.indexOf(reason) + 1})`;

export default function SkipReport({ range, onClose }) {
  const report = useLoad(() => api.skipReport(range), [range.since, range.until]);

  if (report.error && !report.data) return <div className="card"><Empty>{report.error}</Empty></div>;
  if (report.first) return <div className="card"><Empty>Loading…</Empty></div>;

  const { reasons, totals, people, other_reasons: typed } = report.data;
  const skippers = people.filter((p) => p.skipped > 0);
  const top = Math.max(1, ...skippers.map((p) => p.skipped));
  // Only reasons somebody used get a legend entry and a pivot column.
  const used = reasons.filter((r) => totals.by_reason[r] > 0);

  return (
    <div className="card" id="skip-report">
      <header>
        <h2>Skipped jobs</h2>
        <span className="muted small">
          {totals.skipped} skipped of {totals.given} handed over
          {totals.given ? ` · ${pct(totals.rate)}` : ""}
        </span>
        <span className="spacer" />
        {onClose && <button className="link" onClick={onClose}>Close</button>}
      </header>

      <State busy={false} error=""
             empty={totals.skipped === 0 && "Nobody skipped anything in this date range."}>
        <h3 className="muted">By BD, split by reason</h3>
        <div className="legend" aria-label="Reasons">
          {used.map((r) => (
            <span key={r}><i style={{ background: hue(reasons, r) }} />{r}</span>
          ))}
        </div>
        <div className="bars">
          {skippers.map((p) => (
            <SkipBar key={p.user_id ?? "none"} seat={p} top={top}
                     reasons={reasons} used={used} />
          ))}
        </div>

        <h3 className="muted" style={{ marginTop: "var(--s6)" }}>Pivot — BD × reason</h3>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>BD</th>
                {used.map((r) => <th key={r} className="num">{r}</th>)}
                <th className="num">Skipped</th>
                <th className="num">Handed over</th>
                <th className="num">Skip rate</th>
              </tr>
            </thead>
            <tbody>
              {people.map((p) => (
                <tr key={p.user_id ?? "none"}>
                  <td className={p.user_id ? "strong" : "muted"}>{p.name}</td>
                  {used.map((r) => (
                    <td key={r} className={`num ${p.by_reason[r] ? "" : "muted"}`}>
                      {p.by_reason[r] || "—"}
                    </td>
                  ))}
                  <td className="num strong">{p.skipped}</td>
                  <td className="num">{p.given}</td>
                  <td className="num">{p.given ? pct(p.rate) : "—"}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td className="strong">All BDs</td>
                {used.map((r) => <td key={r} className="num strong">{totals.by_reason[r]}</td>)}
                <td className="num strong">{totals.skipped}</td>
                <td className="num strong">{totals.given}</td>
                <td className="num strong">{totals.given ? pct(totals.rate) : "—"}</td>
              </tr>
            </tfoot>
          </table>
        </div>

        {typed.length > 0 && (
          <>
            <h3 className="muted" style={{ marginTop: "var(--s6)" }}>
              &ldquo;Other&rdquo;, as it was typed
            </h3>
            <ul className="typed">
              {typed.map((t) => (
                <li key={t.reason}><span>{t.reason}</span><b>{t.count}</b></li>
              ))}
            </ul>
          </>
        )}
      </State>
    </div>
  );
}

/** One BD: a bar as long as their skips, cut into a segment per reason. */
function SkipBar({ seat, top, reasons, used }) {
  const [tip, setTip] = useState(null);
  const parts = used.filter((r) => seat.by_reason[r] > 0);

  return (
    <div className="bar-row">
      <span className="bar-name" title={seat.name}>{seat.name}</span>
      <div className="bar-track" onMouseLeave={() => setTip(null)}>
        <div className="bar-fill" style={{ width: `${(seat.skipped / top) * 100}%` }}>
          {parts.map((r) => (
            <span key={r} className="seg"
                  style={{ flexGrow: seat.by_reason[r], background: hue(reasons, r) }}
                  aria-label={`${r}: ${seat.by_reason[r]}`}
                  onMouseEnter={() => setTip(r)} />
          ))}
        </div>
        {tip && (
          <div className="bar-tip" role="tooltip">
            <b>{seat.name}</b> · {tip}: {seat.by_reason[tip]} of {seat.skipped}
          </div>
        )}
      </div>
      <span className="bar-value">
        {seat.skipped}<span className="muted"> · {pct(seat.rate)}</span>
      </span>
    </div>
  );
}
