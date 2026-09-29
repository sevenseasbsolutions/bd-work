/* Every call to the server goes through here.
 *
 * One fetch wrapper, one place the token lives, one place a 401 is turned into
 * "you are signed out" — which is the only way the rest of the app gets to be
 * written as if requests always work.
 */

const BASE = import.meta.env.VITE_API || "http://127.0.0.1:8000";
const KEY = "mbs.token";

// A request to a port nothing is listening on does not fail on Windows — the
// connection attempt just sits there — so without a deadline a frontend
// pointed at the wrong API spins on "Signing in…" forever instead of saying
// what is wrong. Exports get longer: they build a workbook before replying.
const TIMEOUT = 20000;
const EXPORT_TIMEOUT = 60000;
// A sheet upload is the one request that is allowed to take minutes: three
// thousand lines is three thousand postings fanned out to every live profile.
// The server commits as it goes, so even a request that does time out here has
// filed what it reached — and uploading the same file again adds only the rest.
const UPLOAD_TIMEOUT = 15 * 60 * 1000;

const unreachable = () =>
  new Error(`Could not reach the API at ${BASE}. Is it running?`);

export const getToken = () => localStorage.getItem(KEY) || "";
export const setToken = (value) => {
  if (value) localStorage.setItem(KEY, value);
  else localStorage.removeItem(KEY);
};

/** A {since, until} range as a query string. Either end may be left out, and
 *  an empty range is no query string at all rather than `?since=&until=`. */
function span(range, extra = "") {
  const parts = extra ? [extra] : [];
  if (range?.since) parts.push(`since=${encodeURIComponent(range.since)}`);
  if (range?.until) parts.push(`until=${encodeURIComponent(range.until)}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

async function call(path, { method = "GET", body } = {}) {
  let reply;
  try {
    reply = await fetch(BASE + path, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(TIMEOUT),
    });
  } catch {
    throw unreachable();
  }

  if (reply.status === 401) {
    // The token is gone or stale. Clear it and let the shell show the gate,
    // rather than every screen inventing its own handling of a dead session.
    setToken("");
    window.dispatchEvent(new CustomEvent("mbs:signed-out"));
    throw new Error("Your session has expired. Sign in again.");
  }

  const text = await reply.text();
  const data = text ? JSON.parse(text) : null;
  if (!reply.ok) {
    const detail = data?.detail;
    // FastAPI validation errors arrive as a list of objects, and the message
    // alone ("String should have at least 4 characters") does not say which
    // box it is about. The field name is the last part of `loc`.
    throw new Error(
      typeof detail === "string" ? detail
        : Array.isArray(detail)
          ? detail.map((d) => {
            const field = d.loc?.[d.loc.length - 1];
            return field && field !== "body" ? `${field}: ${d.msg}` : d.msg;
          }).join(". ")
          : "Something went wrong."
    );
  }
  return data;
}

/** The name the server gave the file.
 *
 * `filename*` is the real one and is percent-encoded UTF-8 — a profile called
 * "Khuram — AI Engineer" has an em dash in it. `filename` is the plain ASCII
 * fallback, used only if the encoded one is missing or will not decode.
 */
function filenameFrom(header) {
  if (!header) return "";
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1]);
    } catch {
      /* malformed — fall through to the plain one */
    }
  }
  const plain = /filename="([^"]+)"/i.exec(header);
  return plain ? plain[1] : "";
}

/** Fetch a file and hand it to the browser to save.
 *
 * A plain link cannot be used: the export routes want the bearer token, and an
 * <a href> carries no headers. So it is fetched, turned into a blob and given
 * to an anchor that is clicked and thrown away.
 */
async function save(path, range, fallbackName) {
  let reply;
  try {
    reply = await fetch(BASE + path + span(range), {
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
      signal: AbortSignal.timeout(EXPORT_TIMEOUT),
    });
  } catch {
    throw unreachable();
  }

  if (reply.status === 401) {
    setToken("");
    window.dispatchEvent(new CustomEvent("mbs:signed-out"));
    throw new Error("Your session has expired. Sign in again.");
  }
  if (!reply.ok) {
    // An error comes back as JSON even from a route that normally sends a file.
    let detail = "That export could not be built.";
    try {
      detail = (await reply.json()).detail || detail;
    } catch {
      /* not JSON — keep the generic message */
    }
    throw new Error(typeof detail === "string" ? detail : "That export could not be built.");
  }

  const blob = await reply.blob();
  const name = filenameFrom(reply.headers.get("content-disposition")) || fallbackName;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Revoked on a delay: revoking immediately can cancel the save in Safari.
  setTimeout(() => URL.revokeObjectURL(url), 30000);
  return name;
}

/** Post a file as multipart/form-data.
 *
 * Deliberately not `call`: the body is a FormData, and setting Content-Type by
 * hand is the classic way to break a multipart request — the browser has to
 * write that header itself, because only it knows the boundary it generated.
 */
async function upload(path, file) {
  const form = new FormData();
  form.append("file", file, file.name);

  let reply;
  try {
    reply = await fetch(BASE + path, {
      method: "POST",
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
      body: form,
      signal: AbortSignal.timeout(UPLOAD_TIMEOUT),
    });
  } catch {
    throw unreachable();
  }

  if (reply.status === 401) {
    setToken("");
    window.dispatchEvent(new CustomEvent("mbs:signed-out"));
    throw new Error("Your session has expired. Sign in again.");
  }

  const text = await reply.text();
  const data = text ? JSON.parse(text) : null;
  if (!reply.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === "string" ? detail
      : "That sheet could not be read.");
  }
  return data;
}

export const api = {
  login: (email, password) => call("/auth/login", { method: "POST", body: { email, password } }),
  me: () => call("/auth/me"),

  users: () => call("/users"),
  addUser: (body) => call("/users", { method: "POST", body }),
  editUser: (id, body) => call(`/users/${id}`, { method: "PATCH", body }),
  removeUser: (id) => call(`/users/${id}`, { method: "DELETE" }),

  platforms: () => call("/platforms"),
  addPlatform: (name) => call("/platforms", { method: "POST", body: { name } }),
  removePlatform: (id) => call(`/platforms/${id}`, { method: "DELETE" }),

  // The counts on a profile row move with the range, so this takes one too.
  profiles: (range) => call(`/profiles${span(range)}`),
  addProfile: (body) => call("/profiles", { method: "POST", body }),
  editProfile: (id, body) => call(`/profiles/${id}`, { method: "PATCH", body }),
  removeProfile: (id) => call(`/profiles/${id}`, { method: "DELETE" }),

  own: (id, range) => call(`/profiles/${id}/own${span(range)}`),
  logOwn: (id, jobs) => call(`/profiles/${id}/own`, { method: "POST", body: { jobs } }),
  // Before filing: which of these lines has this BD applied for already, and
  // when. Writes nothing.
  checkOwn: (id, jobs) =>
    call(`/profiles/${id}/own/check`, { method: "POST", body: { jobs } }),
  dropOwn: (id, applicationId) =>
    call(`/profiles/${id}/own/${applicationId}`, { method: "DELETE" }),

  others: (id, status = "pending", range) =>
    call(`/profiles/${id}/others${span(range, `status=${status}`)}`),
  move: (assignmentId, status, applied_on = "", reason = "") =>
    call(`/assignments/${assignmentId}`,
         { method: "POST", body: { status, applied_on, reason } }),
  // Select all, then Applied or Skip. One request whether it is four rows or
  // four thousand.
  moveMany: (ids, status, applied_on = "", reason = "") =>
    call("/assignments/bulk", { method: "POST", body: { ids, status, applied_on, reason } }),

  // The old sheet, and the record of every one uploaded before it.
  importSheet: (id, file) => upload(`/profiles/${id}/import`, file),
  imports: (id) => call(`/profiles/${id}/imports`),
  exportLeftovers: (importId) =>
    save(`/imports/${importId}/leftovers.xlsx`, null, "MBS left over.xlsx"),
  exportTemplate: () => save("/import-template.xlsx", null, "MBS import template.xlsx"),

  // The manager's switches. Everybody reads them; only a manager writes.
  settings: () => call("/settings"),
  saveSettings: (body) => call("/settings", { method: "PATCH", body }),

  // The Google Sheet mirror. Manager only, all of them.
  sheetStatus: () => call("/sheets"),
  setSheets: (body) => call("/sheets", { method: "PUT", body }),
  syncSheet: (rebuild = false) =>
    call(`/sheets/sync${rebuild ? "?rebuild=true" : ""}`, { method: "POST" }),
  resetSheet: () => call("/sheets/reset", { method: "POST" }),

  allJobs: (id, range) => call(`/profiles/${id}/all${span(range)}`),
  pool: (range) => call(`/jobs${span(range)}`),
  overview: (range) => call(`/overview${span(range)}`),
  skipReport: (range) => call(`/reports/skipped${span(range)}`),

  // Both read through the same date range as the screen they are started from.
  exportProfile: (id, range) =>
    save(`/profiles/${id}/export.xlsx`, range, "MBS profile.xlsx"),
  exportWorkspace: (range) => save("/export.xlsx", range, "MBS workspace.xlsx"),
};
