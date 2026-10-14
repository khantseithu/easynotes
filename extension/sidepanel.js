import { api, getServer, getJobs, post, removeJob, startJob, videoId } from "./lib.js";

const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const dur = s => { const m = Math.round(s / 60), h = Math.floor(m / 60); return h ? `${h}h ${String(m % 60).padStart(2, "0")}m` : `${m}m`; };
const clock = s => { s = Math.max(0, Math.floor(s || 0)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = String(s % 60).padStart(2, "0"); return h ? `${h}:${String(m).padStart(2, "0")}:${x}` : `${m}:${x}`; };
const secsOf = t => t.split(":").reduce((a, p) => a * 60 + +p, 0);
const isUrl = s => /(youtu\.be\/|youtube\.com\/|^[\w-]{11}$)/.test(s.trim());
const local = {
  async get(k, d) { const o = await chrome.storage.local.get(k); return k in o ? o[k] : d; },
  set(k, v) { return chrome.storage.local.set({ [k]: v }); },
};
const ICON = {
  play: `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/></svg>`,
  pause: `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>`,
  headphones: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 15v-3a8 8 0 0 1 16 0v3"/><rect x="3" y="14" width="5" height="7" rx="2"/><rect x="16" y="14" width="5" height="7" rx="2"/></svg>`,
  notes: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h9l4 4v14H6z"/><path d="M9 12h7M9 16h5"/></svg>`,
  watch: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M7 5v14l12-7z"/></svg>`,
};
const SPEEDS = [1, 1.25, 1.5, 1.75, 2];

const state = {
  server: "", windowId: null, tab: null, tabVid: null,
  route: { kind: "tab" }, // "tab" follows the YouTube tab; "library" and "note" are picked by the user
  notes: null, voices: [], note: null, terms: {}, jobs: {},
  minutes: 60, q: "", playing: null, offline: null,
};

// ---------- data ----------

async function loadIndex() {
  try {
    state.notes = await api("/api/notes");
    state.offline = null;
    if (!state.voices.length) state.voices = await api("/api/voices").catch(() => []);
  } catch (e) {
    state.notes = null;
    state.offline = e.message;
  }
}

async function loadTab() {
  const [tab] = await chrome.tabs.query({ active: true, windowId: state.windowId });
  state.tab = tab || null;
  const vid = videoId(tab?.url);
  if (vid !== state.tabVid) {
    state.tabVid = vid;
    if (state.route.kind !== "tab" && vid) state.route = { kind: "tab" };
  }
}

const hasNote = id => state.notes?.some(n => n.id === id);
const tabTitle = () => (state.tab?.title || "").replace(/^\(\d+\)\s*/, "").replace(/\s*-\s*YouTube$/, "");

// ---------- render ----------

async function render() {
  const r = state.route;
  $("#back").hidden = r.kind === "tab" || (r.kind === "library" && !state.tabVid);
  $("#library").setAttribute("aria-pressed", r.kind === "library" || (r.kind === "tab" && !state.tabVid));
  $("#open-app").href = state.server + (r.kind === "note" ? `/#${r.id}` : r.kind === "tab" && hasNote(state.tabVid) ? `/#${state.tabVid}` : "/");
  if (state.offline) return offlineView();
  if (r.kind === "note") return noteView(r.id);
  if (r.kind === "tab" && state.tabVid) return hasNote(state.tabVid) ? noteView(state.tabVid) : makeView(state.tabVid);
  libraryView();
}

function offlineView() {
  $("#view").innerHTML = `
    <div class="card">
      <h1>Start YT Notes</h1>
      <p>The extension can't reach the YT Notes server at <code>${esc(state.server)}</code>. Start it on your Mac:</p>
      <p><code>python3 ytnotes.py --no-open</code></p>
      <p>Then come back here. To use a different address, open Settings.</p>
      <button class="btn primary" id="retry">Try again</button>
      <p class="msg err">${esc(state.offline)}</p>
    </div>`;
  $("#retry").onclick = refresh;
}

function jobFor(vid) { return Object.values(state.jobs).find(j => j.vid === vid); }

function makeView(vid) {
  const job = jobFor(vid);
  const title = tabTitle();
  $("#view").innerHTML = `
    <div class="card">
      <img class="thumb" src="https://i.ytimg.com/vi/${vid}/mqdefault.jpg" alt="">
      ${title ? `<h1>${esc(title)}</h1>` : ""}
      ${job && job.status === "running"
        ? `<button class="btn primary wide" disabled><span class="spin"></span><span>Writing notes…</span></button>
           <div class="progress">${esc(job.message || "Starting…")}</div>`
        : `<p>No notes for this video yet. Notes for a one-hour video take about one minute.</p>
           <button class="btn primary wide" id="make">${ICON.notes}<span>${job ? "Try again" : "Make notes"}</span></button>
           ${job ? `<p class="msg err">${esc(job.message)}</p>` : ""}`}
    </div>`;
  $(".thumb").addEventListener("error", e => e.target.remove(), { once: true });
  const btn = $("#make");
  if (btn) btn.onclick = async () => {
    if (job) await removeJob(job.id);
    btn.disabled = true;
    try {
      await startJob(`https://www.youtube.com/watch?v=${vid}`, state.minutes, vid);
    } catch (e) {
      state.offline = e.message;
    }
    await syncJobs();
    render();
  };
}

function libraryView() {
  const q = state.q.toLowerCase();
  const notes = (state.notes || []).filter(n => !q || `${n.title} ${n.channel}`.toLowerCase().includes(q));
  const jobs = Object.values(state.jobs);
  const saved = (state.notes || []).reduce((a, n) => a + Math.max(0, n.secs - n.read_mins * 60), 0);
  $("#view").innerHTML = `
    <form class="composer" id="composer" autocomplete="off">
      <label class="vh" for="in">YouTube link or topic</label>
      <div class="field"><input id="in" placeholder="YouTube link or topic"><button class="go" id="go" disabled>Make notes</button></div>
      <div class="seg-row" id="seg-row"><span>Cover</span>
        <div class="seg" role="group" aria-label="How much video to cover">
          ${[[30, "30m"], [60, "1h"], [120, "2h"], [240, "4h"]].map(([m, l]) => `<button type="button" data-min="${m}" aria-pressed="${m === state.minutes}">${l}</button>`).join("")}
        </div><span>of video</span></div>
    </form>
    ${jobs.map(j => `<div class="job ${j.status === "error" ? "err" : ""}"><div class="t">${esc(j.label)}</div>
      <div class="m">${j.status === "error" ? "" : `<span class="spin"></span>`}<span>${esc(j.message || "Starting…")}</span>
      ${j.status === "error" ? `<button class="x" data-dismiss="${j.id}">Dismiss</button>` : ""}</div></div>`).join("")}
    <div class="lib-head"><strong>Library</strong><span>${(state.notes || []).length} notes${saved ? ` · ${dur(saved)} saved` : ""}</span></div>
    ${(state.notes || []).length > 6 ? `<input class="filter" id="q" type="search" placeholder="Filter notes" aria-label="Filter notes" value="${esc(state.q)}">` : ""}
    <ul class="list">${notes.length ? notes.map(n => `<li><button class="item" data-id="${n.id}">
      <div class="t">${esc(n.title)}</div><div class="m"><span>${esc(n.channel)}</span><span>${n.read_mins} min read</span>${n.audio ? "<span>Audio</span>" : ""}</div></button></li>`).join("")
      : `<li class="empty">${q ? "No notes match." : "No notes yet. Open a YouTube video, or paste a link above."}</li>`}</ul>`;
  const input = $("#in");
  input.oninput = () => { $("#go").disabled = !input.value.trim(); $("#seg-row").classList.toggle("on", !!input.value.trim() && !isUrl(input.value)); };
  $("#seg-row").onclick = e => { const b = e.target.closest("[data-min]"); if (b) { state.minutes = +b.dataset.min; local.set("minutes", state.minutes); libraryView(); } };
  $("#composer").onsubmit = async e => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    try { await startJob(text, state.minutes, videoId(text) || (/^[\w-]{11}$/.test(text) ? text : null)); } catch (err) { state.offline = err.message; }
    await syncJobs();
    render();
  };
  $("#q")?.addEventListener("input", e => {
    state.q = e.target.value;
    const pos = e.target.selectionStart;
    libraryView();
    $("#q").focus();
    $("#q").setSelectionRange(pos, pos);
  });
  $("#view").querySelectorAll("[data-id]").forEach(b => b.onclick = () => { state.route = { kind: "note", id: b.dataset.id }; render(); scrollTo({ top: 0 }); });
  $("#view").querySelectorAll("[data-dismiss]").forEach(b => b.onclick = async () => { await removeJob(b.dataset.dismiss); await syncJobs(); render(); });
}

let shown = null;
async function noteView(id) {
  if (shown === id && $("#md")) return renderActions();
  shown = id;
  $("#view").innerHTML = `<div style="padding-top:20px"><div class="sk" style="width:40%"></div><div class="sk" style="height:24px;width:85%"></div><div class="sk"></div><div class="sk" style="width:92%"></div><div class="sk" style="width:70%"></div></div>`;
  let n;
  try { n = await api(`/api/notes/${id}`); } catch (e) { shown = null; state.offline = e.message; return render(); }
  if (shown !== id) return;
  state.note = n;
  const saved = Math.max(0, n.secs - n.read_mins * 60);
  $("#view").innerHTML = `
    <div class="kicker"><span>${esc(n.channel)}</span><span>${dur(n.secs)} video</span><span>${n.read_mins} min read</span>${saved ? `<span class="saved">${dur(saved)} saved</span>` : ""}</div>
    <h1>${esc(n.title)}</h1>
    <div class="actions" id="actions"></div>
    <div class="md" id="md">${DOMPurify.sanitize(marked.parse(n.markdown))}</div>`;
  enhance($("#md"), n, new Set(await local.get(`done:${n.id}`, [])));
  renderActions();
  scrollTo({ top: 0 });
  followVideo();
}

// ---------- note body ----------

function enhance(root, n, done) {
  root.querySelectorAll("h3 a").forEach(a => {
    if (/^\d{1,2}(:\d{2}){1,2}$/.test(a.textContent.trim())) { a.className = "ts"; a.setAttribute("aria-label", `Watch from ${a.textContent}`); }
  });
  root.querySelectorAll("li a, p a").forEach(a => { if (/^\d{1,2}(:\d{2}){1,2}$/.test(a.textContent.trim())) a.className = "ts-inline"; });
  root.querySelectorAll("a").forEach(a => { a.target = "_blank"; a.rel = "noopener"; });

  root.querySelectorAll('li > input[type="checkbox"]').forEach((box, i) => {
    const li = box.parentElement;
    li.classList.add("task");
    const span = document.createElement("span");
    while (box.nextSibling) span.appendChild(box.nextSibling);
    li.appendChild(span);
    box.disabled = false;
    box.checked = done.has(i);
    box.setAttribute("aria-label", span.textContent.trim());
    box.onchange = () => { box.checked ? done.add(i) : done.delete(i); local.set(`done:${n.id}`, [...done]); };
  });

  const gh = [...root.querySelectorAll("h2")].find(h => /glossary/i.test(h.textContent));
  const terms = [];
  if (gh && gh.nextElementSibling?.tagName === "UL") {
    const dl = document.createElement("dl");
    dl.className = "glossary";
    [...gh.nextElementSibling.children].forEach(li => {
      const strong = li.querySelector("strong");
      if (!strong) return;
      const term = strong.textContent.trim();
      const rest = li.innerHTML.slice(li.innerHTML.indexOf("</strong>") + 9).replace(/^\s*/, "");
      const m = rest.match(/^\(([^)]*)\)\s*:?\s*([\s\S]*)$/) || [null, "", rest.replace(/^:\s*/, "")];
      const id = "g-" + term.toLowerCase().replace(/[^a-z0-9]+/g, "-");
      const def = m[2].replace(/^:\s*/, "");
      dl.insertAdjacentHTML("beforeend", `<dt id="${id}">${esc(term)}</dt><dd>${m[1] ? `<span class="full">${esc(m[1])}.</span> ` : ""}${def}</dd>`);
      const tmp = document.createElement("div"); tmp.innerHTML = def;
      terms.push({ term, id, full: m[1], def: tmp.textContent });
    });
    gh.nextElementSibling.replaceWith(dl);
    linkTerms(root, gh, terms);
  }
  state.terms = Object.fromEntries(terms.map(t => [t.id, t]));
}

function linkTerms(root, stopAt, terms) {
  const sorted = terms.filter(t => t.term.length > 1).sort((a, b) => b.term.length - a.term.length);
  const used = new Set();
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (stopAt.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING) return NodeFilter.FILTER_REJECT;
      return node.parentElement.closest("a, h1, h2, h3, code, .term") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const t of sorted) {
    const re = new RegExp(`(?<![\\w-])${t.term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![\\w-])`, /[A-Z]{2}/.test(t.term) ? "" : "i");
    for (let i = 0; i < nodes.length && !used.has(t.id); i++) {
      const node = nodes[i];
      const m = node.data.match(re);
      if (!m) continue;
      const after = node.splitText(m.index);
      const rest = after.splitText(m[0].length);
      const a = document.createElement("a");
      a.className = "term"; a.href = `#${t.id}`; a.dataset.id = t.id; a.textContent = m[0];
      after.replaceWith(a);
      nodes.splice(i, 1, node, rest);
      used.add(t.id);
    }
  }
}

const pop = $("#pop");
let popFor = null;
function showPop(a) {
  const t = state.terms[a.dataset.id];
  if (!t) return;
  popFor = a;
  pop.innerHTML = `<b>${esc(t.term)}</b>${t.full ? `<span class="full">${esc(t.full)}</span>` : ""}${esc(t.def)}`;
  pop.classList.add("on");
  const r = a.getBoundingClientRect(), pw = pop.offsetWidth, ph = pop.offsetHeight;
  const left = Math.min(Math.max(16, r.left + scrollX + r.width / 2 - pw / 2), scrollX + innerWidth - pw - 16);
  let top = r.bottom + scrollY + 8;
  if (r.bottom + ph + 16 > innerHeight - player.offsetHeight) top = r.top + scrollY - ph - 8;
  pop.style.left = left + "px"; pop.style.top = top + "px";
}
function hidePop() { pop.classList.remove("on"); popFor = null; }
document.addEventListener("mouseover", e => { const a = e.target.closest(".term"); if (a) showPop(a); });
document.addEventListener("mouseout", e => { if (e.target.closest(".term") && !e.relatedTarget?.closest?.(".term")) hidePop(); });
document.addEventListener("focusin", e => { const a = e.target.closest?.(".term"); if (a) showPop(a); });

// Timestamps seek the video in the tab when it is the same video; otherwise they open it.
document.addEventListener("click", async e => {
  const term = e.target.closest(".term");
  if (term) { e.preventDefault(); popFor === term ? hidePop() : showPop(term); return; }
  if (!e.target.closest(".pop")) hidePop();
  const a = e.target.closest("#md a[href]");
  if (!a) return;
  const u = new URL(a.href);
  const vid = videoId(a.href);
  if (!vid) return;
  e.preventDefault();
  const secs = +(u.searchParams.get("t") || "0").replace(/s$/, "") || 0;
  await watch(vid, secs);
});

async function watch(vid, secs = 0) {
  const tab = state.tab;
  if (tab && state.tabVid === vid) {
    const ok = await chrome.tabs.sendMessage(tab.id, { type: "seek", secs }).then(r => r?.ok, () => false);
    if (ok) return;
  }
  const url = `https://www.youtube.com/watch?v=${vid}${secs ? `&t=${secs}s` : ""}`;
  if (tab && /^https:\/\/(www|m)\.youtube\.com\//.test(tab.url || "")) chrome.tabs.update(tab.id, { url });
  else chrome.tabs.create({ url, windowId: state.windowId });
}

// Mark the key idea that the video is playing now.
let followTimer = null;
function followVideo() {
  clearInterval(followTimer);
  const heads = [...document.querySelectorAll("#md h3")].map(h => ({ h, secs: h.querySelector(".ts") ? secsOf(h.querySelector(".ts").textContent.trim()) : null }))
    .filter(x => x.secs !== null);
  if (!heads.length) return;
  const tick = async () => {
    if (!state.note || state.note.id !== state.tabVid || !$("#md")) return heads.forEach(x => x.h.classList.remove("now"));
    const r = await chrome.tabs.sendMessage(state.tab.id, { type: "time" }).catch(() => null);
    if (!r?.ok) return;
    const cur = heads.filter(x => x.secs <= r.secs + 1).pop();
    heads.forEach(x => x.h.classList.toggle("now", x === cur && (r.secs > 0 || !r.paused)));
  };
  tick();
  followTimer = setInterval(tick, 2000);
}

// ---------- audio ----------

const audio = $("#audio");
const player = $("#player");
let voicePref = null;
function voiceOf() { return state.voices.some(x => x.id === voicePref) ? voicePref : state.voices[0]?.id; }

function renderActions(msg, kind, pct) {
  const n = state.note;
  if (!n || !$("#actions")) return;
  const voice = voiceOf();
  const ready = n.audio && n.audio.voice === voice;
  const isPlaying = state.playing?.id === n.id && !audio.paused;
  const busy = msg && kind !== "err";
  const label = busy ? msg : kind === "err" ? "Try again" : ready ? (isPlaying ? "Pause" : state.playing?.id === n.id ? "Resume" : "Listen") : n.audio ? "Record in this voice" : `Listen · ~${Math.max(1, Math.round(n.read_mins * 1.3))} min`;
  $("#actions").innerHTML = `
    <button class="btn primary" id="listen" ${busy ? "disabled" : ""}>
      <span class="fill" style="width:${pct || 0}%"></span>${busy ? `<span class="spin"></span>` : isPlaying ? ICON.pause : ICON.headphones}<span>${esc(label)}</span>
    </button>
    ${state.voices.length ? `<label class="vh" for="voice">Voice</label>
    <select class="voice" id="voice">${state.voices.map(v => `<option value="${v.id}" ${v.id === voice ? "selected" : ""}>${esc(v.label)}</option>`).join("")}</select>` : ""}
    ${state.tabVid === n.id ? "" : `<button class="btn" id="watch">${ICON.watch}<span>Watch</span></button>`}
    ${kind === "err" ? `<p class="msg err" style="flex-basis:100%;margin:0">${esc(msg)}</p>` : ""}`;
  $("#voice")?.addEventListener("change", e => { voicePref = e.target.value; local.set("voice", voicePref); renderActions(); });
  $("#watch")?.addEventListener("click", () => watch(n.id));
  $("#listen").onclick = () => {
    if (ready) return state.playing?.id === n.id ? togglePlay() : play(n);
    record(n);
  };
}

async function record(n) {
  const voice = voiceOf();
  renderActions("Starting…", null, 0);
  try {
    let job = await post(`/api/audio/${n.id}`, { voice });
    while (job.status === "running") {
      await new Promise(r => setTimeout(r, 800));
      job = await api(`/api/jobs/${job.id}`);
      const pct = +(job.message.match(/(\d+)%/) || [])[1] || 0;
      if (state.note?.id === n.id) renderActions(job.message.replace(/…?\s*\d+%/, "").replace(/…$/, "") + (pct ? ` ${pct}%` : "…"), null, pct);
    }
    if (job.status === "error") throw new Error(job.message);
    const fresh = await api(`/api/notes/${n.id}`);
    if (state.note?.id === n.id) state.note = { ...state.note, audio: fresh.audio };
    await loadIndex();
    play(fresh);
  } catch (e) {
    if (state.note?.id === n.id) renderActions(e.message, "err");
  }
}

function setPlayerH() { document.documentElement.style.setProperty("--player-h", (player.classList.contains("on") ? player.offsetHeight : 0) + "px"); }
async function play(n) {
  if (state.playing?.id !== n.id) {
    state.playing = n;
    audio.src = `${state.server}/audio/${n.id}.m4a?v=${n.audio.voice}`;
    const resume = await local.get(`pos:${n.id}`, 0);
    audio.addEventListener("loadedmetadata", () => { if (resume && resume < audio.duration - 5) audio.currentTime = resume; }, { once: true });
    $("#p-title").textContent = n.title;
    navigator.mediaSession.metadata = new MediaMetadata({ title: n.title, artist: n.channel, album: "YT Notes" });
  }
  audio.playbackRate = await local.get("speed", 1);
  player.classList.add("on");
  setPlayerH();
  audio.play().catch(() => {});
}
function togglePlay() { audio.paused ? audio.play() : audio.pause(); }
function syncPlayer() {
  $("#p-play").innerHTML = audio.paused ? ICON.play : ICON.pause;
  $("#p-play").setAttribute("aria-label", audio.paused ? "Play" : "Pause");
  renderActions();
}
$("#p-play").onclick = togglePlay;
$("#p-title").onclick = () => { if (state.playing) { state.route = { kind: "note", id: state.playing.id }; render(); } };
$("#p-close").onclick = () => { audio.pause(); player.classList.remove("on"); state.playing = null; setPlayerH(); renderActions(); };
$("#p-speed").onclick = async () => {
  const next = SPEEDS[(SPEEDS.indexOf(await local.get("speed", 1)) + 1) % SPEEDS.length];
  local.set("speed", next); audio.playbackRate = next; $("#p-speed").textContent = `${next}×`;
};
let seeking = false;
$("#p-seek").addEventListener("input", e => { seeking = true; $("#p-cur").textContent = clock(e.target.value / 100 * audio.duration); });
$("#p-seek").addEventListener("change", e => { audio.currentTime = e.target.value / 100 * audio.duration; seeking = false; });
audio.addEventListener("play", syncPlayer);
audio.addEventListener("pause", syncPlayer);
audio.addEventListener("loadedmetadata", () => { $("#p-dur").textContent = clock(audio.duration); });
let lastSave = 0;
audio.addEventListener("timeupdate", () => {
  if (!seeking && audio.duration) { $("#p-seek").value = audio.currentTime / audio.duration * 100; $("#p-cur").textContent = clock(audio.currentTime); }
  if (state.playing && Date.now() - lastSave > 4000) { local.set(`pos:${state.playing.id}`, audio.currentTime); lastSave = Date.now(); }
});
audio.addEventListener("ended", () => { if (state.playing) local.set(`pos:${state.playing.id}`, 0); syncPlayer(); });
new ResizeObserver(setPlayerH).observe(player);

// ---------- jobs ----------

async function syncJobs() { state.jobs = await getJobs(); schedulePoll(); }

let pollTimer = null;
function schedulePoll() {
  clearTimeout(pollTimer);
  if (Object.values(state.jobs).some(j => j.status === "running")) pollTimer = setTimeout(poll, 1500);
}

async function poll() {
  let finished = false;
  for (const job of Object.values(state.jobs).filter(j => j.status === "running")) {
    let j;
    try { j = await api(`/api/jobs/${job.id}`); } catch (e) {
      j = { status: "error", message: /not found/i.test(e.message) ? "The YT Notes server restarted. Try again." : e.message };
    }
    const jobs = await getJobs();
    if (!jobs[job.id]) continue;
    if (j.status === "done") { delete jobs[job.id]; finished = true; }
    else jobs[job.id] = { ...jobs[job.id], status: j.status, message: j.message };
    await chrome.storage.session.set({ jobs });
  }
  state.jobs = await getJobs();
  if (finished) { await loadIndex(); chrome.runtime.sendMessage({ type: "notes-changed" }).catch(() => {}); }
  if (!$("#md")) render();
  schedulePoll();
}

// ---------- wiring ----------

async function refresh() {
  state.server = await getServer();
  await Promise.all([loadIndex(), loadTab(), syncJobs()]);
  render();
}

$("#library").onclick = () => { state.route = { kind: "library" }; render(); };
$("#back").onclick = () => { state.route = state.route.kind === "note" ? { kind: "library" } : { kind: "tab" }; render(); };
$("#settings").onclick = () => chrome.runtime.openOptionsPage();

chrome.tabs.onActivated.addListener(({ windowId }) => { if (windowId === state.windowId) loadTab().then(render); });
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (tabId !== state.tab?.id) return;
  if (change.url) loadTab().then(render);
  else if (change.title && state.route.kind === "tab" && state.tabVid && !hasNote(state.tabVid)) loadTab().then(render);
});
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "session" && changes.jobs) syncJobs().then(() => { if (!$("#md")) render(); });
  if (area === "sync" && changes.server) { shown = null; refresh(); }
});

(async () => {
  state.windowId = (await chrome.windows.getCurrent()).id;
  state.minutes = await local.get("minutes", 60);
  voicePref = await local.get("voice", null);
  $("#p-speed").textContent = `${await local.get("speed", 1)}×`;
  syncPlayer();
  refresh();
})();
