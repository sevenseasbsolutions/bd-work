/* The handful of parts every screen is built from. */
import React, { createContext, useCallback, useContext, useEffect, useState } from "react";

/* ── Toasts ───────────────────────────────────────────────────────────── */

const Toasts = createContext(() => {});
export const useToast = () => useContext(Toasts);

export function ToastHost({ children }) {
  const [items, setItems] = useState([]);

  const push = useCallback((text, tone = "ok") => {
    const id = Math.random().toString(36).slice(2);
    setItems((all) => [...all, { id, text, tone }]);
    setTimeout(() => setItems((all) => all.filter((t) => t.id !== id)), 4000);
  }, []);

  return (
    <Toasts.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.tone === "bad" ? "bad" : ""}`}>{t.text}</div>
        ))}
      </div>
    </Toasts.Provider>
  );
}

/* ── Theme ────────────────────────────────────────────────────────────── */

export function ThemeToggle() {
  const [theme, setTheme] = useState(() => localStorage.getItem("mbs.theme") || "");

  useEffect(() => {
    if (theme) document.documentElement.setAttribute("data-theme", theme);
    else document.documentElement.removeAttribute("data-theme");
    localStorage.setItem("mbs.theme", theme);
  }, [theme]);

  // Three states, one button: follow the system, then light, then dark. The
  // label says which one is on rather than which one is next.
  const next = { "": "light", light: "dark", dark: "" };
  const label = { "": "Auto", light: "Light", dark: "Dark" };
  return (
    <button className="link" onClick={() => setTheme(next[theme])}
            title="Light, dark, or follow the system">{label[theme]}</button>
  );
}

/* ── Pieces ───────────────────────────────────────────────────────────── */

export const Tile = ({ value, label, accent }) => (
  <div className={`tile ${accent ? "accent" : ""}`}>
    <b>{value}</b><span>{label}</span>
  </div>
);

export const Chip = ({ kind, children }) => (
  <span className={`chip ${kind || ""}`}>{children}</span>
);

export const Empty = ({ children }) => <div className="empty">{children}</div>;

/** The job link, shown as the link — not hidden behind the job title.
 *
 * Only http(s) is ever turned into an anchor, so nothing in the data can
 * smuggle a javascript: URL onto the page. The protocol and www. are dropped
 * from what is displayed because they are the same on every row; the full
 * address is on hover and is what the anchor actually points at.
 */
export function UrlCell({ url }) {
  const safe = /^https?:\/\//i.test(url || "") ? url : "";
  if (!safe) return <span className="muted">—</span>;
  const shown = safe.replace(/^https?:\/\//i, "").replace(/^www\./i, "");
  return (
    <a className="url" href={safe} title={safe} target="_blank" rel="noreferrer noopener">
      {shown}
    </a>
  );
}

/* ── Searching a list of jobs ─────────────────────────────────────────── */

// Query parameters that name the posting rather than the search that found it.
// The same idea, and the same short list, as the server's `_ID_PARAMS`: on
// Indeed, ADP and Workday the job id lives nowhere but the query string, so
// dropping the whole query to compare two links makes every posting on the
// site look like the same one.
const ID_PARAMS = new Set([
  "jobid", "jobno", "jobcode", "currentjobid", "vjk", "jk", "gh_jid",
  "postingid", "requisitionid", "reqid", "vacancyid", "positionid",
]);

/** A link with everything that differs between two spellings of one address
 *  taken off: the protocol, the www, the fragment, the trailing slash and any
 *  query parameter that is tracking rather than identity. */
const bareUrl = (value) => {
  const text = String(value || "").trim().toLowerCase()
    .replace(/^https?:\/\//, "").replace(/^www\./, "").split("#")[0];
  if (!text) return "";
  const [head, query = ""] = text.split("?");
  const kept = query.split("&")
    .map((pair) => pair.split("="))
    .filter(([key, value2]) => value2 && ID_PARAMS.has(key))
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value2]) => `${key}=${value2}`);
  return head.replace(/\/+$/, "") + (kept.length ? `?${kept.join("&")}` : "");
};

/** Whether one job matches what was typed in the search box.
 *
 * Title, client, finder — and the link. Searching by link matters because the
 * link is the one thing about a posting that is unambiguous: two people can
 * write a client's name three ways, but they are holding the same URL.
 *
 * Two passes. The first is a plain substring, which catches a job id typed on
 * its own ("~017acdef") or a bare host. The second is for a whole address
 * pasted in: the copy in somebody's address bar usually carries a referral
 * tail the stored one does not, so both sides go through `bareUrl` first.
 */
export function jobMatches(job, query) {
  const needle = String(query || "").trim().toLowerCase();
  if (!needle) return true;

  const url = bareUrl(job.url);
  const haystack =
    `${job.title || ""} ${job.company || ""} ${job.found_by || ""} ${url}`.toLowerCase();
  if (haystack.includes(needle)) return true;

  // Short fragments are left to the substring pass above: matching a two-letter
  // stem against every path in the pool would hand back the whole list.
  const pasted = bareUrl(needle);
  return pasted.length > 4 && url.includes(pasted);
}

/* ── Dates ────────────────────────────────────────────────────────────── */

/** Today as YYYY-MM-DD, in the reader's own timezone.
 *  `toISOString` would be UTC, which puts an evening in Karachi on tomorrow. */
export function today() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

const daysAgo = (n) => {
  const then = new Date();
  then.setDate(then.getDate() - n);
  const pad = (x) => String(x).padStart(2, "0");
  return `${then.getFullYear()}-${pad(then.getMonth() + 1)}-${pad(then.getDate())}`;
};

export const ALL_TIME = { since: "", until: "" };

/** Today and nothing else — where every screen opens. A fresh object each
 *  call, so a screen left open past midnight picks up the new day on reload. */
export const TODAY = () => ({ since: today(), until: today() });

// The five answers to "from when?" that people actually want, plus the two
// boxes for the fifth. `since: 6` days back is seven days counting today.
const PRESETS = [
  ["Today", TODAY],
  ["All time", () => ALL_TIME],
  ["Last 7 days", () => ({ since: daysAgo(6), until: today() })],
  ["Last 30 days", () => ({ since: daysAgo(29), until: today() })],
  ["This month", () => ({ since: today().slice(0, 8) + "01", until: today() })],
];

const same = (a, b) => a.since === b.since && a.until === b.until;

/** From this day to that day. Whatever it is set to, every list and every
 *  count on the screen is read through it.
 *
 *  `children` sit at the right-hand end of the strip. The export button goes
 *  there on every screen, because what it hands you is exactly the window this
 *  control is set to, and that is easier to see than to explain. */
export function DateRange({ value, onChange, children }) {
  const set = (key) => (e) => onChange({ ...value, [key]: e.target.value });

  return (
    <div className="wrap-row range" role="group" aria-label="Date range">
      {PRESETS.map(([label, make]) => {
        const target = make();
        return (
          <button key={label} className={`btn sm ${same(value, target) ? "primary" : ""}`}
                  onClick={() => onChange(target)}>{label}</button>
        );
      })}
      <span className="muted small">Day</span>
      {/* One day, the one most people want when they reach for a date: sets
          both ends at once rather than making them type it twice. */}
      <input type="date" className="day" aria-label="One day"
             value={value.since && value.since === value.until ? value.since : ""}
             onChange={(e) => onChange({ since: e.target.value, until: e.target.value })} />
      <span className="muted small">or from</span>
      <input type="date" className="day" value={value.since} max={value.until || undefined}
             onChange={set("since")} aria-label="From date" />
      <span className="muted small">to</span>
      <input type="date" className="day" value={value.until} min={value.since || undefined}
             onChange={set("until")} aria-label="To date" />
      {!same(value, TODAY()) && (
        <button className="link" onClick={() => onChange(TODAY())}>Back to today</button>
      )}
      {children && (
        <span className="row" style={{ gap: "var(--s2)", marginLeft: "auto" }}>
          {children}
        </span>
      )}
    </div>
  );
}

/** Downloads a workbook, and says so. Disabled while it is being built, since
 *  a second press would only start a second identical download. */
export function ExportButton({ run, label = "Export to Excel", small = false,
                               title = "Everything in the date range above, as an .xlsx file" }) {
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  return (
    <button className={`btn ${small ? "sm" : ""}`} disabled={busy} title={title}
            onClick={async () => {
              setBusy(true);
              try {
                toast(`Downloaded ${await run()}`);
              } catch (e) {
                toast(e.message, "bad");
              } finally {
                setBusy(false);
              }
            }}>
      {busy ? "Building…" : label}
    </button>
  );
}

/* ── Copying to a spreadsheet ─────────────────────────────────────────── */

/** Cells joined the way a spreadsheet reads them back: tabs between columns,
 *  newlines between rows. A cell holding either would split itself in two, so
 *  both are flattened to a space first. */
export const asRow = (cells) =>
  cells.map((cell) => String(cell ?? "").replace(/[\t\r\n]+/g, " ").trim()).join("\t");

export async function copyText(text) {
  // The async clipboard API needs a secure context — https or localhost, which
  // covers every way this app is served. The textarea is for the rest.
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const pad = document.createElement("textarea");
    pad.value = text;
    pad.style.cssText = "position:fixed;top:-1000px;opacity:0";
    document.body.appendChild(pad);
    pad.select();
    const ok = document.execCommand("copy");
    pad.remove();
    return ok;
  }
}

/** Copies, then says so on the button itself for a second.
 *  A toast for something this small would be louder than the action. */
export function CopyButton({ text, label = "Copy", title = "Copy this row — paste it straight into Excel" }) {
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (!done) return undefined;
    const timer = setTimeout(() => setDone(false), 1400);
    return () => clearTimeout(timer);
  }, [done]);

  return (
    <button className={`btn sm ${done ? "ok" : ""}`} title={title}
            onClick={async () => setDone(await copyText(typeof text === "function" ? text() : text))}>
      {done ? "Copied" : label}
    </button>
  );
}

export function Field({ label, ...rest }) {
  return (
    <div className="field">
      <label>{label}</label>
      <input type="text" {...rest} />
    </div>
  );
}

/** A confirm that is one click plus one, without a modal to build or dismiss.
 *  The second press is the confirmation, and it reverts if nothing follows. */
export function Danger({ onConfirm, children, title = "Delete permanently" }) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return undefined;
    const timer = setTimeout(() => setArmed(false), 3500);
    return () => clearTimeout(timer);
  }, [armed]);

  return (
    <button className={`btn sm ${armed ? "bad" : ""}`} title={title}
            onClick={() => (armed ? onConfirm() : setArmed(true))}>
      {armed ? "Sure?" : children}
    </button>
  );
}

/** What a list says while it is loading, and what it says if it broke. */
export function State({ busy, error, empty, children }) {
  if (error) return <Empty>{error}</Empty>;
  if (busy) return <Empty>Loading…</Empty>;
  if (empty) return <Empty>{empty}</Empty>;
  return children;
}

/** Load something, and re-load it whenever `deps` change or reload() is called.
 *
 * `first` is busy with nothing to show yet, and it is the one screens should
 * put a spinner behind. Hanging one on plain `busy` swaps the whole screen for
 * "Loading…" on every refresh, which unmounts what is under it — and anything
 * half-typed inside it goes with it.
 */
export function useLoad(loader, deps = []) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let live = true;
    setBusy(true);
    setError("");
    Promise.resolve()
      .then(loader)
      .then((value) => live && setData(value))
      .catch((e) => live && setError(e.message))
      .finally(() => live && setBusy(false));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { data, busy, first: busy && data === null, error,
           reload: () => setNonce((n) => n + 1) };
}
