import { api, startJob, videoId } from "./lib.js";

const YT = ["https://www.youtube.com/*", "https://m.youtube.com/*", "https://youtu.be/*"];
let index = { at: 0, ids: new Set() };

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "notes-link", title: "Make notes with YT Notes", contexts: ["link"], targetUrlPatterns: YT });
  chrome.contextMenus.create({ id: "notes-page", title: "Make notes for this video", contexts: ["page", "video"], documentUrlPatterns: YT });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const vid = videoId(info.menuItemId === "notes-link" ? info.linkUrl : info.pageUrl);
  if (!vid) return;
  // sidePanel.open needs the user gesture, so call it before anything async.
  if (tab?.id !== undefined) chrome.sidePanel.open({ tabId: tab.id }).catch(() => {});
  startJob(`https://www.youtube.com/watch?v=${vid}`, 60, vid).catch(e => {
    chrome.action.setBadgeText({ tabId: tab?.id, text: "!" });
    chrome.action.setTitle({ tabId: tab?.id, title: `YT Notes: ${e.message}` });
  });
});

// Mark the toolbar icon on videos that already have notes.
async function noteIds() {
  if (Date.now() - index.at > 30000) {
    try {
      index = { at: Date.now(), ids: new Set((await api("/api/notes")).map(n => n.id)) };
    } catch {
      index = { at: Date.now(), ids: new Set() };
    }
  }
  return index.ids;
}

async function badge(tabId, url) {
  const vid = videoId(url);
  const has = vid && (await noteIds()).has(vid);
  chrome.action.setBadgeBackgroundColor({ tabId, color: "#3f56b2" });
  chrome.action.setBadgeText({ tabId, text: has ? "✓" : "" });
  chrome.action.setTitle({ tabId, title: has ? "YT Notes: notes ready for this video" : "YT Notes" });
}

chrome.tabs.onUpdated.addListener((tabId, change, tab) => { if (change.url || change.status === "complete") badge(tabId, tab.url); });
chrome.tabs.onActivated.addListener(({ tabId }) => chrome.tabs.get(tabId).then(t => badge(tabId, t.url)).catch(() => {}));
chrome.runtime.onMessage.addListener(msg => {
  if (msg?.type !== "notes-changed") return;
  index.at = 0;
  chrome.tabs.query({ active: true }).then(tabs => tabs.forEach(t => badge(t.id, t.url)));
});
