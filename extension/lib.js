export const DEFAULT_SERVER = "http://127.0.0.1:8765";

export async function getServer() {
  const { server } = await chrome.storage.sync.get("server");
  return (server || DEFAULT_SERVER).replace(/\/+$/, "");
}

export async function api(path, opts) {
  const r = await fetch((await getServer()) + path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

export const post = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

// The video on a YouTube page (watch, shorts, live, embed or youtu.be), or null.
export function videoId(url) {
  if (!url) return null;
  try {
    const u = new URL(url);
    if (u.hostname === "youtu.be") return /^[\w-]{11}$/.test(u.pathname.slice(1)) ? u.pathname.slice(1) : null;
    if (!/(^|\.)youtube\.com$/.test(u.hostname)) return null;
    if (u.pathname === "/watch") return /^[\w-]{11}$/.test(u.searchParams.get("v") || "") ? u.searchParams.get("v") : null;
    const m = u.pathname.match(/^\/(?:shorts|live|embed)\/([\w-]{11})/);
    return m ? m[1] : null;
  } catch {
    return null;
  }
}

// Jobs that the server is running, kept in session storage so they survive the side panel closing.
export async function getJobs() {
  const { jobs } = await chrome.storage.session.get("jobs");
  return jobs || {};
}

export async function addJob(job) {
  const jobs = await getJobs();
  jobs[job.id] = job;
  await chrome.storage.session.set({ jobs });
}

export async function removeJob(id) {
  const jobs = await getJobs();
  delete jobs[id];
  await chrome.storage.session.set({ jobs });
}

export async function startJob(input, minutes, level, vid = null) {
  const j = await post("/api/jobs", { input, minutes, level, vid });
  const job = { id: j.id, vid, label: input, message: j.message, status: j.status, started: Date.now() };
  await addJob(job);
  return job;
}
