"""A daily list of new videos worth watching, picked from channels you chose instead of YouTube's recommendations."""
import json
import re
import subprocess
import threading
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import llm

UA = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US"}
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}
MAX_PICKS = 8
WINDOW_DAYS = 3
LOCK = threading.Lock()

RANK_PROMPT = """Pick the new YouTube videos that are worth this person's time today. They want to learn and think,
and they use this list instead of YouTube's recommendations, so be stricter than an algorithm that wants watch time.

What they chose to read before, from their notes library (title · channel):
{taste}

New uploads from channels they trust, as JSON (mins = length, hours = hours since upload, about = start of the description):
{candidates}

Pick at most {n}. Keep videos with real substance: ideas, evidence, skills, or experience that the viewer can use.
Skip clickbait, reactions, recaps of news, trailers, announcements, sponsor-led videos, and stream replays with no clear topic.
Skip a video that repeats another pick. Prefer what fits their interests above. Picking fewer is fine, and so is picking none.
For each pick, write one plain-English line of under 20 words that says what the viewer gets from it. No hype and no emoji.
Reply with only a JSON array, best first, like [{{"id": "VIDEO_ID", "why": "..."}}]."""


class Store:
    def __init__(self, notes_dir):
        self.notes = Path(notes_dir)
        self.sources_file = self.notes / "sources.json"
        self.dir = self.notes / "daily"

    def sources(self):
        return json.loads(self.sources_file.read_text()) if self.sources_file.exists() else []

    def save_sources(self, items):
        self.notes.mkdir(exist_ok=True)
        self.sources_file.write_text(json.dumps(items, indent=2, ensure_ascii=False))

    def add(self, found):
        with LOCK:
            items = [s for s in self.sources() if s["id"] != found["id"]]
            items.append({**found, "added": datetime.now().isoformat(timespec="seconds")})
            self.save_sources(items)
        return items

    def remove(self, cid):
        with LOCK:
            items = self.sources()
            left = [s for s in items if s["id"] != cid]
            self.save_sources(left)
        return len(left) < len(items)

    def list_for(self, day):
        f = self.dir / f"{day}.json"
        return json.loads(f.read_text()) if f.exists() else None

    def latest(self):
        files = sorted(self.dir.glob("*.json")) if self.dir.exists() else []
        return json.loads(files[-1].read_text()) if files else None

    def shown_before(self, day):
        files = sorted(self.dir.glob("*.json")) if self.dir.exists() else []
        return {p["id"] for f in files if f.stem != day for p in json.loads(f.read_text())["picks"]}

    def save_list(self, data):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / f"{data['date']}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))


def resolve(text):
    """Turn a channel link, an @handle, a channel id or a video link into {id, name}."""
    text = text.strip()
    if re.fullmatch(r"UC[\w-]{22}", text):
        url = f"https://www.youtube.com/channel/{text}"
    elif text.startswith("@"):
        url = f"https://www.youtube.com/{text}"
    elif re.fullmatch(r"[\w-]{11}", text):
        url = f"https://www.youtube.com/watch?v={text}"
    else:
        url = text if text.startswith("http") else "https://" + text
    out = subprocess.run(["yt-dlp", "-J", "--flat-playlist", "--playlist-items", "1", "--no-warnings", url],
                         capture_output=True, text=True, timeout=120)
    try:
        info = json.loads(out.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Could not find a YouTube channel for {text}")
    cid = info.get("channel_id") or ""
    if not re.fullmatch(r"UC[\w-]{22}", cid):
        raise RuntimeError(f"Could not find a YouTube channel for {text}")
    name = info.get("channel") or info.get("uploader") or cid
    return {"id": cid, "name": re.sub(r" - (Videos|Home)$", "", name)}


def seed(store, notes):
    """Add the channels of the notes library as sources. Uses the channel id that the note saved, or looks it up."""
    have = {s["id"] for s in store.sources()}
    names = {s["name"] for s in store.sources()}
    picks = {}
    for n in notes:
        if n["channel"] and n["channel"] not in names and n["channel"] not in picks:
            picks[n["channel"]] = n.get("channel_id") or n["id"]
    with ThreadPoolExecutor(4) as ex:
        found = list(ex.map(lambda v: _safe_resolve(v), picks.values()))
    added = [f for f in found if f and f["id"] not in have]
    for f in {f["id"]: f for f in added}.values():
        store.add(f)
    return len({f["id"] for f in added})


def _safe_resolve(text):
    try:
        return resolve(text)
    except Exception:
        return None


def get(url, timeout=20):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read().decode()


def feed(source):
    """New uploads of a channel from its RSS feed. The UULF playlist feed leaves out Shorts and live streams."""
    tail = source["id"][2:]
    entries, shorts_ok = [], False
    for url in (f"https://www.youtube.com/feeds/videos.xml?playlist_id=UULF{tail}",
                f"https://www.youtube.com/feeds/videos.xml?channel_id={source['id']}"):
        try:
            root = ET.fromstring(get(url))
        except Exception:
            continue
        entries = root.findall("a:entry", NS)
        shorts_ok = "playlist_id" in url
        break
    out = []
    for e in entries:
        link = e.find("a:link", NS)
        if not shorts_ok and link is not None and "/shorts/" in link.get("href", ""):
            continue
        desc = e.find("media:group/media:description", NS)
        out.append({
            "id": e.findtext("yt:videoId", "", NS),
            "title": e.findtext("a:title", "", NS),
            "channel": source["name"],
            "channel_id": source["id"],
            "published": e.findtext("a:published", "", NS),
            "about": re.sub(r"\s+", " ", (desc.text or "") if desc is not None else "")[:300],
        })
    return out


def length(vid):
    """The video length in seconds from its watch page, or None. 0 means a live stream or a premiere."""
    try:
        html = get(f"https://www.youtube.com/watch?v={vid}")
    except Exception:
        return None
    if '"isUpcoming":true' in html or '"isLiveNow":true' in html:
        return 0
    m = re.search(r'"lengthSeconds":"(\d+)"', html)
    return int(m.group(1)) if m else None


def build(store, notes, model, day=None, log=print):
    day = day or date.today().isoformat()
    sources = store.sources()
    if not sources:
        raise RuntimeError("Add a channel first")
    log(f"Checking {len(sources)} channels…")
    with ThreadPoolExecutor(8) as ex:
        uploads = [v for vs in ex.map(_safe_feed, sources) for v in vs]
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    skip = {n["id"] for n in notes} | store.shown_before(day)
    fresh = {}
    for v in uploads:
        try:
            when = datetime.fromisoformat(v["published"])
        except ValueError:
            continue
        if v["id"] and when >= since and v["id"] not in skip:
            fresh[v["id"]] = {**v, "hours": round((datetime.now(timezone.utc) - when).total_seconds() / 3600)}
    pool = list(fresh.values())
    log(f"Reading {len(pool)} new videos…")
    with ThreadPoolExecutor(8) as ex:
        for v, secs in zip(pool, ex.map(length, [v["id"] for v in pool])):
            v["secs"] = secs
    # Under 2 minutes is a Short that the feed did not mark, and 0 is a stream that has not ended.
    pool = [v for v in pool if v["secs"] is None or v["secs"] >= 120]
    data = {"date": day, "created": datetime.now().isoformat(timespec="seconds"), "channels": len(sources),
            "considered": len(pool), "picks": []}
    if pool:
        log(f"Picking from {len(pool)} new videos…")
        data["picks"], error = rank(pool, notes, model)
        if error:
            data["error"] = error
    store.save_list(data)
    return data


def _safe_feed(source):
    try:
        return feed(source)
    except Exception:
        return []


def rank(pool, notes, model, n=MAX_PICKS):
    taste = "\n".join(f"- {x['title']} · {x['channel']}" for x in notes[:40]) or "- (no notes yet)"
    short = [{"id": v["id"], "title": v["title"], "channel": v["channel"], "hours": v["hours"],
              "mins": round(v["secs"] / 60) if v["secs"] else None, "about": v["about"]} for v in pool]
    prompt = RANK_PROMPT.format(taste=taste, candidates=json.dumps(short, ensure_ascii=False), n=n)
    by_id = {v["id"]: v for v in pool}
    try:
        res = llm.run(prompt, model, timeout=300)
        if res.returncode != 0:
            raise RuntimeError((res.stderr.strip() or "model failed").splitlines()[-1][:200])
        picks = json.loads(re.search(r"\[.*\]", res.stdout, re.S).group(0))
        out = [{**_pick(by_id[p["id"]]), "why": str(p.get("why", "")).strip()} for p in picks
               if isinstance(p, dict) and p.get("id") in by_id]
        return list({p["id"]: p for p in out}.values())[:n], None
    except Exception as e:
        newest = sorted(pool, key=lambda v: v["hours"])[:n]
        return [{**_pick(v), "why": ""} for v in newest], f"The model could not rank the videos ({e}), so these are the newest."


def _pick(v):
    return {k: v[k] for k in ("id", "title", "channel", "channel_id", "published", "secs")}


def view(data, notes):
    noted = {n["id"] for n in notes}
    return {**data, "picks": [{**p, "noted": p["id"] in noted} for p in data["picks"]]}
