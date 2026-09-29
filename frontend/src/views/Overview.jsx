/* The manager's numbers, and only the manager's numbers.
 *
 * Five counts, per BD and per profile, in the same five words the BD screens
 * use. A manager and a BD disagreeing about what "applied" means is the
 * failure this screen is shaped to avoid.
 */
import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import SkipReport from "./SkipReport.jsx";
import { TODAY, today, DateRange, Empty, ExportButton, State, Tile, useLoad } from "./ui.jsx";

export default function Overview({ onOpenPeople }) {
  const [range, setRange] = useState(TODAY);
  const board = useLoad(() => api.overview(range), [range.since, range.until]);
  // The skipped report, opened from the Skipped tile or any Skipped number.
  const [skips, setSkips] = useState(false);
  useEffect(() => {
    if (skips) document.getElementById("skip-report")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [skips]);
  const openSkips = () => setSkips(true);

  if (board.error && !board.data) return <Empty>{board.error}</Empty>;
  if (board.first) return <Empty>Loading…</Empty>;

  const { totals, people, profiles } = board.data;

  return (
    <>
      <div style={{ marginBottom: "var(--s5)" }}>
        <DateRange value={range} onChange={setRange}>
          <ExportButton label="Export everything"
                        run={() => api.exportWorkspace(range)} />
        </DateRange>
      </div>

      <div className="card">
        <header>
          <h1>Where the work is</h1>
          <span className="muted small">
            {range.since || range.until
              ? (range.since === range.until
                ? `Every number below is ${range.since === today() ? "today's" : `for ${range.since}`}.`
                : "Every number below is read through the range above.")
              : "Everything, all the time — there is no cycle to open."}
          </span>
        </header>
        <div className="tiles">
          <Tile value={totals.applied} label="applied in all" accent />
          <Tile value={totals.own} label="own jobs found" />
          <Tile value={totals.from_others} label="others' jobs applied for" />
          <button type="button" className="tile" aria-pressed={skips}
                  title="Who skipped, and why" onClick={() => setSkips(!skips)}>
            <b>{totals.skipped}</b><span>skipped · <em>{skips ? "hide report" : "see why"}</em></span>
          </button>
          <Tile value={totals.pending} label="still pending" />
          <Tile value={totals.jobs} label="jobs in the pool" />
        </div>
        {(totals.unassigned > 0 || totals.profiles === 0) && (
          <p className="muted small" style={{ marginBottom: 0 }}>
            {totals.profiles === 0
              ? "No profiles yet — nothing can be dispatched until there are some."
              : `${totals.unassigned} profile${totals.unassigned === 1 ? "" : "s"} nobody holds, so nobody is working ${totals.unassigned === 1 ? "it" : "them"}.`}
            {onOpenPeople && <> <button className="link" onClick={onOpenPeople}>Open People</button></>}
          </p>
        )}
      </div>

      {skips && <SkipReport range={range} onClose={() => setSkips(false)} />}

      <div className="card">
        <header>
          <h2>By BD</h2>
          <span className="muted small">Their profiles added together.</span>
        </header>
        <State busy={false} error="" empty={people.length === 0 && "No profiles are assigned yet."}>
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>BD</th><th>Profiles</th>
                  <th className="num">Own jobs</th>
                  <th className="num">Others&apos; given</th>
                  <th className="num">Others&apos; applied</th>
                  <th className="num">Skipped</th>
                  <th className="num">Pending</th>
                  <th className="num">Applied in all</th>
                </tr>
              </thead>
              <tbody>
                {people.map((seat) => (
                  <tr key={seat.user_id}>
                    <td className="strong">{seat.name}</td>
                    <td className="muted small">{seat.profiles.join(", ")}</td>
                    <td className="num">{seat.own}</td>
                    <td className="num">{seat.given}</td>
                    <td className="num">{seat.from_others}</td>
                    <td className="num">
                      {seat.skipped
                        ? <button className="link" onClick={openSkips}>{seat.skipped}</button>
                        : 0}
                    </td>
                    <td className="num">{seat.pending}</td>
                    <td className="num strong">{seat.applied}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </State>
      </div>

      <div className="card">
        <header>
          <h2>By profile</h2>
          <span className="muted small">The unit of work — one person may run several.</span>
        </header>
        <State busy={false} error="" empty={profiles.length === 0 && "No profiles yet."}>
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>Profile</th><th>Held by</th>
                  <th className="num">Own jobs</th>
                  <th className="num">Others&apos; given</th>
                  <th className="num">Others&apos; applied</th>
                  <th className="num">Skipped</th>
                  <th className="num">Pending</th>
                  <th className="num">Applied in all</th>
                </tr>
              </thead>
              <tbody>
                {profiles.map((p) => (
                  <tr key={p.id} style={p.is_active ? undefined : { opacity: 0.55 }}>
                    <td>
                      <span className="strong">{p.name}</span>
                      {!p.is_active && <span className="muted small"> · off</span>}
                      {p.headline && <span className="muted small"><br />{p.headline}</span>}
                    </td>
                    <td className={p.bd ? "" : "muted"}>{p.bd || "nobody"}</td>
                    <td className="num">{p.counts.own}</td>
                    <td className="num">{p.counts.given}</td>
                    <td className="num">{p.counts.from_others}</td>
                    <td className="num">{p.counts.skipped}</td>
                    <td className="num">{p.counts.pending}</td>
                    <td className="num strong">{p.counts.applied}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </State>
      </div>
    </>
  );
}
