/* The shell: who is signed in, which screen they are on, and the two things
 * that sit above every screen — toasts and the theme.
 */
import React, { useCallback, useEffect, useState } from "react";
import { api, getToken, setToken } from "./api.js";
import Login from "./views/Login.jsx";
import BdWork from "./views/BdWork.jsx";
import Overview from "./views/Overview.jsx";
import People from "./views/People.jsx";
import Pool from "./views/Pool.jsx";
import { Empty, ThemeToggle, ToastHost } from "./views/ui.jsx";

const TABS = {
  // A manager reads three screens and writes on one of them. That is the whole
  // job: there is no cycle to start, because the workspace is always open.
  manager: [
    ["overview", "Overview"],
    ["people", "People"],
    ["jobs", "All jobs"],
    ["work", "Profiles"],
  ],
  bd: [["work", "My work"]],
};

/** The two spreadsheets, one click from every manager screen.
 *
 *  In the bar rather than on a screen because they are not about any one of
 *  them: a manager who lives in the sheet wants it open, and hunting for the
 *  link on the People screen every morning is the reason they would stop
 *  bothering. Silent when there is no sheet — a header is no place to explain
 *  a setting.
 */
function SheetLinks() {
  const [where, setWhere] = useState({});
  useEffect(() => {
    api.sheetStatus().then(setWhere).catch(() => setWhere({}));
  }, []);
  const both = [
    ["My sheet", where.manager_url, "Your four screens, in a file of your own"],
    ["Team sheet", where.team_url, "A tab per BD — everything they applied for"],
  ].filter(([, url]) => url);
  if (!both.length) return null;
  return (
    <span className="row" style={{ gap: "var(--s2)", whiteSpace: "nowrap" }}>
      {both.map(([label, url, why]) => (
        <a key={label} className="link" href={url} target="_blank"
           rel="noreferrer" title={why}>{label} ↗</a>
      ))}
    </span>
  );
}

export default function App() {
  const [user, setUser] = useState(null);
  const [view, setView] = useState("overview");
  const [booting, setBooting] = useState(true);

  const signOut = useCallback(() => {
    setToken("");
    setUser(null);
    setView("overview");
  }, []);

  // api.js fires this when a request comes back 401, so a session that died on
  // the server takes the app back to the gate without any screen knowing.
  useEffect(() => {
    window.addEventListener("mbs:signed-out", signOut);
    return () => window.removeEventListener("mbs:signed-out", signOut);
  }, [signOut]);

  useEffect(() => {
    if (!getToken()) {
      setBooting(false);
      return;
    }
    api.me()
      .then((me) => {
        setUser(me);
        setView(me.role === "manager" ? "overview" : "work");
      })
      .catch(() => setToken(""))
      .finally(() => setBooting(false));
  }, []);

  if (booting) return <div className="wrap"><Empty>Loading…</Empty></div>;

  if (!user) {
    return (
      <ToastHost>
        <Login onSignedIn={(me) => {
          setUser(me);
          setView(me.role === "manager" ? "overview" : "work");
        }} />
      </ToastHost>
    );
  }

  const isManager = user.role === "manager";
  const tabs = TABS[user.role] || TABS.bd;

  return (
    <ToastHost>
      <header className="top">
        <span className="brand">MBS</span>
        <nav className="tabs" aria-label="Sections">
          {tabs.map(([key, label]) => (
            <button key={key} className="tab" aria-current={view === key}
                    onClick={() => setView(key)}>{label}</button>
          ))}
        </nav>
        <span className="spacer" />
        {isManager && <SheetLinks />}
        <span className="muted small" style={{ whiteSpace: "nowrap" }}>{user.name}</span>
        <ThemeToggle />
        <button className="link" onClick={signOut}>Sign out</button>
      </header>

      {/* Keyed on the view so a switch replays the entrance once, for the whole
          screen, rather than animating every row that arrives. */}
      <main className="wrap enter" key={view}>
        {isManager
          ? (view === "people" ? <People />
            : view === "jobs" ? <Pool />
              : view === "work" ? <BdWork readOnly />
                : <Overview onOpenPeople={() => setView("people")} />)
          : <BdWork />}
      </main>
    </ToastHost>
  );
}
