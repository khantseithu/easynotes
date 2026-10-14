#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US"}

PROMPT = """You are summarizing a YouTube video for someone learning "{topic}" who is short on time.
Video: "{title}" by {channel}

From the transcript on stdin, write:
- One line: what this video is really about.
- 3 to 5 bullet takeaways, concrete and actionable (frameworks, numbers, tactics). No fluff.
- One line starting with "Skip if:" saying who doesn't need to watch it.

Plain markdown, no headings, under 150 words."""

RANK_PROMPT = """Someone wants to learn "{topic}" and has {minutes} minutes total.
Below are YouTube search results as JSON (secs = length, views, published = age).

Pick the videos that best teach this specific topic. Prefer substantive talks, interviews
and practical playbooks from credible practitioners; reject generic explainers of adjacent
concepts, clickbait, ads and off-topic results. Avoid two videos covering the same thing.
Total secs must not exceed {budget}. Order them so they build on each other.

Reply with only a JSON array of video ids, nothing else.

{candidates}"""


def parse_duration(text):
    secs = 0
    for part in text.split(":"):
        secs = secs * 60 + int(part)
    return secs


def parse_views(text):
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def fmt_duration(secs):
    h, m = divmod(round(secs / 60), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def search(query):
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    html = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read().decode()
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", html)
    if not m:
        return []
    found = []

    def walk(o):
        if isinstance(o, dict):
            v = o.get("videoRenderer")
            if v and "lengthText" in v:
                found.append({
                    "id": v["videoId"],
                    "title": v["title"]["runs"][0]["text"],
                    "channel": v.get("ownerText", {}).get("runs", [{}])[0].get("text", ""),
                    "views": parse_views(v.get("viewCountText", {}).get("simpleText", "")),
                    "secs": parse_duration(v["lengthText"]["simpleText"]),
                    "published": v.get("publishedTimeText", {}).get("simpleText", ""),
                })
            for x in o.values():
                walk(x)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(json.loads(m.group(1)))
    return found


def candidates(topic, budget_secs, min_views, max_secs):
    queries = [topic, f"{topic} explained", f"{topic} talk", f"how to {topic}"]
    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(lambda q: search_safe(q), queries))
    seen, pool = set(), []
    for batch in results:
        for v in batch:
            if v["id"] in seen:
                continue
            seen.add(v["id"])
            if v["views"] >= min_views and 240 <= v["secs"] <= min(max_secs, budget_secs):
                pool.append(v)
    pool.sort(key=lambda v: v["views"], reverse=True)
    return pool


def fill(pool, budget_secs, per_channel):
    chosen, used, channels = [], 0, {}
    for v in pool:
        if used + v["secs"] > budget_secs or channels.get(v["channel"], 0) >= per_channel:
            continue
        chosen.append(v)
        used += v["secs"]
        channels[v["channel"]] = channels.get(v["channel"], 0) + 1
    return chosen


def rank(topic, pool, budget_secs, per_channel, model):
    short = [{k: v[k] for k in ("id", "title", "channel", "secs", "views", "published")} for v in pool[:40]]
    prompt = RANK_PROMPT.format(topic=topic, minutes=budget_secs // 60, budget=budget_secs,
                                candidates=json.dumps(short, ensure_ascii=False))
    try:
        out = subprocess.run(["claude", "-p", prompt, "--model", model],
                             capture_output=True, text=True, timeout=300).stdout
        ids = json.loads(re.search(r"\[.*\]", out, re.S).group(0))
    except Exception as e:
        print(f"  ranking failed ({e}), falling back to views", file=sys.stderr)
        return fill(pool, budget_secs, per_channel)
    by_id = {v["id"]: v for v in pool}
    ordered = [by_id[i] for i in ids if i in by_id]
    return fill(ordered, budget_secs, per_channel)


def search_safe(query):
    try:
        return search(query)
    except Exception as e:
        print(f"  search failed for {query!r}: {e}", file=sys.stderr)
        return []


def transcript(video_id, workdir, attempts=2):
    for _ in range(attempts):
        text = fetch_transcript(video_id, workdir)
        if text:
            return text
    return ""


def fetch_transcript(video_id, workdir):
    subprocess.run(
        ["yt-dlp", "--skip-download", "--write-auto-subs", "--write-subs",
         "--sub-langs", "en.*,en", "--sub-format", "json3", "--quiet", "--no-warnings",
         "-o", str(Path(workdir) / "%(id)s"), f"https://www.youtube.com/watch?v={video_id}"],
        capture_output=True, timeout=120,
    )
    files = sorted(Path(workdir).glob(f"{video_id}*.json3"))
    if not files:
        return ""
    data = json.loads(files[0].read_text())
    words = "".join(s.get("utf8", "") for e in data.get("events", []) for s in e.get("segs", []))
    return re.sub(r"\s+", " ", words).strip()


def summarize(v, topic, model, workdir):
    text = transcript(v["id"], workdir)
    if not text:
        return "_No transcript available._"
    prompt = PROMPT.format(topic=topic, title=v["title"], channel=v["channel"])
    try:
        out = subprocess.run(
            ["claude", "-p", prompt, "--model", model],
            input=text[:80000], capture_output=True, text=True, timeout=300,
        )
        return out.stdout.strip() or f"_Summary failed: {out.stderr.strip()[:200]}_"
    except Exception as e:
        return f"_Summary failed: {e}_"


def render(topic, budget_secs, videos, summaries):
    ids = ",".join(v["id"] for v in videos)
    link = f"https://www.youtube.com/watch_videos?video_ids={ids}"
    total = sum(v["secs"] for v in videos)
    lines = [
        f"# {topic}",
        "",
        f"{len(videos)} videos · {fmt_duration(total)} (budget {fmt_duration(budget_secs)}) · {date.today()}",
        "",
        f"**▶ [Play all]({link})**",
        "",
        "| # | Video | Channel | Length | Views |",
        "|---|---|---|---|---|",
    ]
    for i, v in enumerate(videos, 1):
        lines.append(f"| {i} | [{v['title']}](https://youtu.be/{v['id']}) | {v['channel']} | {fmt_duration(v['secs'])} | {v['views']:,} |")
    if summaries:
        lines += ["", "## Takeaways", ""]
        for i, (v, s) in enumerate(zip(videos, summaries), 1):
            lines += [f"### {i}. {v['title']}", "", s, ""]
    return "\n".join(lines), link


def main():
    ap = argparse.ArgumentParser(description="Build a time-boxed YouTube learning playlist with takeaways.")
    ap.add_argument("topic")
    ap.add_argument("-t", "--time", type=int, default=60, help="time budget in minutes (default 60)")
    ap.add_argument("--min-views", type=int, default=10000)
    ap.add_argument("--max-length", type=int, default=45, help="longest single video in minutes (default 45)")
    ap.add_argument("--per-channel", type=int, default=1)
    ap.add_argument("--no-summary", action="store_true")
    ap.add_argument("--no-rank", action="store_true", help="skip AI picking, rank by views only")
    ap.add_argument("--model", default="claude-haiku-5-5")
    ap.add_argument("-o", "--out", help="output markdown path")
    args = ap.parse_args()

    budget = args.time * 60
    print(f"Searching YouTube for {args.topic!r}...", file=sys.stderr)
    pool = candidates(args.topic, budget, args.min_views, args.max_length * 60)
    if pool and not args.no_rank:
        print(f"Picking the best of {len(pool)} candidates...", file=sys.stderr)
        videos = rank(args.topic, pool, budget, args.per_channel, args.model)
    else:
        videos = fill(pool, budget, args.per_channel)
    if not videos:
        sys.exit("No videos matched. Try a broader topic, more --time, or lower --min-views.")

    summaries = []
    if not args.no_summary:
        print(f"Summarizing {len(videos)} videos...", file=sys.stderr)
        with tempfile.TemporaryDirectory() as workdir, ThreadPoolExecutor(4) as ex:
            summaries = list(ex.map(lambda v: summarize(v, args.topic, args.model, workdir), videos))

    md, link = render(args.topic, budget, videos, summaries)
    out = Path(args.out or f"playlists/{re.sub(r'[^a-z0-9]+', '-', args.topic.lower()).strip('-')}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    print(f"\nPlay all: {link}\nSaved:    {out}")


if __name__ == "__main__":
    main()
