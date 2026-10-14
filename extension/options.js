import { DEFAULT_SERVER, getServer } from "./lib.js";

const input = document.getElementById("server");
const msg = document.getElementById("msg");
const say = (text, err) => { msg.textContent = text; msg.className = err ? "msg err" : "msg"; };

getServer().then(s => { input.value = s; });

document.getElementById("form").addEventListener("submit", async e => {
  e.preventDefault();
  let url;
  try {
    url = new URL(input.value.trim() || DEFAULT_SERVER);
    if (!/^https?:$/.test(url.protocol)) throw new Error();
  } catch {
    return say("Type an address that starts with http:// or https://", true);
  }
  const server = url.origin;
  // 127.0.0.1 and localhost are allowed at install time; other hosts need the user's permission.
  if (!["127.0.0.1", "localhost"].includes(url.hostname)) {
    const ok = await chrome.permissions.request({ origins: [`${server}/*`] }).catch(() => false);
    if (!ok) return say("Chrome did not allow the extension to reach that address.", true);
  }
  await chrome.storage.sync.set({ server });
  input.value = server;
  try {
    const r = await fetch(`${server}/api/notes`);
    if (!r.ok) throw new Error(r.statusText);
    const notes = await r.json();
    say(`Saved. Connected: ${notes.length} notes in your library.`);
  } catch {
    say("Saved, but the server does not answer. Check that it is running.", true);
  }
});
