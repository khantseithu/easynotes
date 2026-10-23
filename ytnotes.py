#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
import unicodedata
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import context
import daily
import llm
import transcript
import ytlearn

ROOT = Path(__file__).resolve().parent
NOTES = ROOT / "notes"
INDEX = NOTES / "index.json"
COLLECTIONS = NOTES / "collections.json"
FRAMES = NOTES / "frames"
MAX_PLAYLIST = 50
SKIP_LISTS = ("RD", "WL", "LL", "UL")
DEFAULT_MODEL = llm.DEFAULT_MODEL
LOCK = threading.Lock()
TTS_LOCK = threading.Lock()
JOBS = {}
DAILY = daily.Store(NOTES)
DAILY_JOB = {}
VOICES = [
    ("af_heart", "Heart · US female"), ("af_bella", "Bella · US female"),
    ("am_michael", "Michael · US male"), ("am_fenrir", "Fenrir · US male"),
    ("bf_emma", "Emma · UK female"), ("bm_george", "George · UK male"),
]
SECTION_INTROS = {"tl;dr": "In short.", "key ideas": "Key ideas.", "frameworks": "Frameworks.",
                  "quotes": "A few memorable quotes.", "action items": "Action items.", "glossary": "Glossary.",
                  "goal": "The goal.", "prerequisites": "What you need.", "steps": "The steps.",
                  "gotchas": "Gotchas.", "result": "The result."}
KINDS = ("conversation", "talk", "tutorial")
GLOSSARY_SECTION = """## Glossary
Every abbreviation and acronym used anywhere in the notes above (e.g. LTV, CAC, ARR, ICP, PLG), plus industry jargon
a smart newcomer to the field would not know (e.g. churn, payback period). Skip everyday words, product names and analogies entirely: never list a skipped term or comment on what you skipped.
Sort alphabetically, as "- **TERM** (full name, if it is an abbreviation): one clear {language} sentence explaining it, in the context of this video."
Omit this section only if the notes use no such terms."""

NOTES_PROMPT = """Turn the YouTube transcript on stdin into notes good enough that the reader does not need to watch the video.

Video: "{title}" by {channel} ({duration})

Write the notes in the requested output language.

Write markdown in exactly this structure:

## TL;DR
2-3 sentences: the core argument and why it matters.

## Key ideas
For each major idea, a ### heading ending with the timestamp where it starts, like "### Why channels saturate [12:34]".
Under it, tight bullets with the real substance: frameworks, steps, numbers, examples, names, and the reasoning behind claims.
Keep the speaker's specifics. Drop filler, sponsor reads, intros and outros.

## Frameworks
Only if the video teaches named models or step-by-step processes. Lay each out clearly. Omit this section otherwise.

## Quotes
2-4 short memorable lines, verbatim, each followed by its timestamp.

## Action items
Concrete things to do, as "- [ ] ..." checkboxes.

""" + GLOSSARY_SECTION.format(language="English") + """

Length should match the substance: about 300 words for a 10-minute video, up to about 1500 for a long interview.
Use only what is in the transcript, except glossary definitions, which may use general knowledge. Timestamps must come from the [mm:ss] markers in the transcript.
Output only the notes."""

GLOSSARY_PROMPT = """The notes on stdin were written from a YouTube video. Write a glossary for them.

Output only the "## Glossary" section, or nothing if there are no such terms."""

TUTORIAL_PROMPT = """Turn the YouTube tutorial on stdin into notes that let the reader follow along and build the same thing
without watching the whole video. They should only need to watch a short clip when a step is hard to follow.

Video: "{title}" by {channel} ({duration}, published {published})

Write the notes in the requested output language.

Write markdown in exactly this structure:

## Goal
2-3 sentences: what the reader builds or learns, and the approach the video takes.

## Prerequisites
Bullets: the tools, languages, libraries, accounts and keys the tutorial needs, with versions when the video or the sources name them.

## Steps
Numbered steps in the order the video does them. Give each step a ### heading that starts with its number and ends with
the timestamp where it starts, like "### 3. Add the database schema [12:34]".
Under each heading, write what to do in short imperative sentences, one instruction per sentence, and state any condition before the instruction.
Add the exact commands and code the step needs in fenced code blocks with a language tag.
Show only the code the step adds or changes, not whole files, unless the file is short.
Say which file each code block belongs to.

## Gotchas
Bullets: the errors, warnings and pitfalls that the presenter hits or mentions, each with its fix and timestamp. Omit this section if there are none.

## Result
What the reader has at the end, and the next steps or extensions that the video suggests.

""" + GLOSSARY_SECTION.format(language="English") + """

Sources. Stdin can contain these blocks before the transcript:
- "Chapters": the video's own chapters. Use them to shape the steps, but split or merge chapters when a step needs it.
- "Linked sources": the repos, gists and docs pages linked in the video description.
Take code, commands, file names and versions from the linked sources when they match what the video does, because the
transcript cannot show what is on screen. If a step needs code that is in neither the transcript nor the sources,
write your best reconstruction and add the line "_Reconstructed from the transcript. Check it against the video._" under the block.
If the sources and the video disagree, follow the video and say what the source does differently.
Timestamps must come from the [mm:ss] markers in the transcript. Glossary definitions may use general knowledge.
Output only the notes."""

KIND_PROMPT = """Classify the YouTube video described on stdin. Answer with one word:
- tutorial: the viewer is shown how to build, code, configure or use something step by step (coding walkthroughs and hands-on product demos count).
- talk: one speaker presents or lectures on a topic, with no hands-on steps to follow.
- conversation: an interview, podcast, panel or discussion between people.
Output only the word."""


def simple_english_rules():
    path = ROOT / "skills" / "simple-english" / "SKILL.md"
    if not path.exists():
        return ""
    text = path.read_text()
    section = text.split("## The Document", 1)[-1].split("## The Reply", 1)[0]
    rules = "\n".join(l for l in section.splitlines() if "references/" not in l).split("\nBefore (AI output):", 1)[0].strip()
    check = text.split("## Self-Check Before You Deliver", 1)[-1].split("## Modes", 1)[0]
    doc_check = next((l for l in check.splitlines() if l.startswith("2. Document:")), "")
    return f"""

Writing rules (the simple-english skill, plain mode). Apply them to every sentence you write.
The required structure above wins where the two conflict: keep its headings, bullets, checkboxes, timestamps and bold glossary terms.
Never change verbatim quotes, numbers, names or facts.

<simple-english>
{rules}

Self-check: {doc_check.removeprefix("2. Document: ")}
</simple-english>"""


WRITING_RULES = simple_english_rules()


def output_language_rules(language):
    if language == "my":
        return """
Write in clear, natural Burmese for a Burmese reader. Use Burmese for explanations and prose, including glossary definitions.
Keep the required English markdown section headings exactly as written so the app can recognize them. Tutorial step headings may be Burmese.
Write all explanatory prose in Burmese. Keep Latin text only for names, technical terms, code, commands, file names, versions, numbers, and verbatim source text where appropriate. Explain technical terms in Burmese; include the original English term when that helps identify it. Do not use unrelated scripts, or include drafting, translation, or self-review remarks. Return only the requested note.
"""
    return "Write in English.\n" + WRITING_RULES


def notes_prompt(kind, language):
    prompt = TUTORIAL_PROMPT if kind == "tutorial" else NOTES_PROMPT
    section = GLOSSARY_SECTION.format(language="Burmese" if language == "my" else "English")
    prompt = prompt.replace(GLOSSARY_SECTION.format(language="English"), section)
    return prompt + "\n\n" + output_language_rules(language)


def glossary_prompt(language):
    section = GLOSSARY_SECTION.format(language="Burmese" if language == "my" else "English")
    return GLOSSARY_PROMPT + "\n\n" + section + "\n\n" + output_language_rules(language)


def video_id(text):
    text = text.strip()
    m = re.search(r"(?:v=|youtu\.be/|shorts/|live/|embed/)([\w-]{11})", text)
    if m:
        return m.group(1)
    return text if re.fullmatch(r"[\w-]{11}", text) else None


def stamp(secs):
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def video_info(vid):
    out = subprocess.run(["yt-dlp", "-j", "--skip-download", "--no-warnings", f"https://www.youtube.com/watch?v={vid}"],
                         capture_output=True, text=True, timeout=180)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def api_transcript(vid, language="en"):
    out = subprocess.run(["uvx", "-q", "--from", "youtube-transcript-api==1.2.4", "youtube_transcript_api", vid,
                          "--languages", language, "--format", "json"], capture_output=True, text=True, timeout=180)
    try:
        return [(c["start"], c["text"]) for c in json.loads(out.stdout)[0]]
    except (json.JSONDecodeError, IndexError, KeyError, TypeError):
        return []


def fetch(vid, workdir):
    info = video_info(vid)
    if not info:
        return None, None, None
    langs, api_languages = transcript.caption_languages(info.get("language"))
    subprocess.run(
        ["yt-dlp", "--skip-download", "--write-info-json", "--write-auto-subs", "--write-subs",
         "--sub-langs", langs, "--sub-format", "json3", "--quiet", "--no-warnings",
         "-o", str(Path(workdir) / "%(id)s"), f"https://www.youtube.com/watch?v={vid}"],
        capture_output=True, timeout=180,
    )
    info_file = Path(workdir) / f"{vid}.info.json"
    info = json.loads(info_file.read_text()) if info_file.exists() else info
    subs = transcript.order_caption_files(list(Path(workdir).glob(f"{vid}*.json3")), vid, info.get("language"))
    segments = []
    transcript_language = "my" if (info.get("language") or "").lower().startswith("my") else "en"
    for sub in subs:
        try:
            data = json.loads(sub.read_text())
        except json.JSONDecodeError:
            continue
        segments = [(e.get("tStartMs", 0) / 1000, "".join(s.get("utf8", "") for s in e.get("segs", [])))
                    for e in data.get("events", [])]
        if any(text.strip() for _, text in segments):
            suffix = sub.name[len(vid) + 1:-len(".json3")]
            if suffix.startswith("my"):
                transcript_language = "my"
            break
        segments = []
    if not segments:
        for language in api_languages:
            segments = api_transcript(vid, language)
            if segments:
                if language == "my":
                    transcript_language = "my"
                break
    if not segments:
        return None, None, None
    meta = {
        "id": vid,
        "title": info.get("title", vid),
        "channel": info.get("channel") or info.get("uploader", ""),
        "channel_id": info.get("channel_id") or "",
        "secs": info.get("duration") or 0,
        "language": transcript_language,
    }
    date = info.get("upload_date") or ""
    if re.fullmatch(r"\d{8}", date):
        meta["published"] = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    extra = {"chapters": context.chapters(info), "description": info.get("description") or ""}
    lines, bucket, start = [], [], None
    for t, text in segments:
        text = text.strip()
        if not text:
            continue
        if start is None:
            start = t
        bucket.append(text)
        if t - start >= 30:
            lines.append(f"[{stamp(start)}] " + re.sub(r"\s+", " ", " ".join(bucket)))
            bucket, start = [], None
    if bucket:
        lines.append(f"[{stamp(start or 0)}] " + re.sub(r"\s+", " ", " ".join(bucket)))
    return meta, "\n".join(lines), extra


def outside_code(md, fn):
    """Apply fn to the parts of md that are not fenced code blocks."""
    parts = re.split(r"(^```.*?^```[^\n]*$)", md, flags=re.S | re.M)
    return "".join(p if i % 2 else fn(p) for i, p in enumerate(parts))


def clean_glossary(md):
    return outside_code(md, lambda t: "\n".join(l for l in t.split("\n") if not re.search(r"\(\s*[^)]*\bomit", l, re.I)))


def link_stamps(md, vid):
    def repl(m):
        parts = [int(p) for p in m.group(1).split(":")]
        secs = 0
        for p in parts:
            secs = secs * 60 + p
        return f"[{m.group(1)}](https://youtu.be/{vid}?t={secs})"
    return outside_code(md, lambda t: re.sub(r"\[(\d{1,2}(?::\d{2}){1,2})\](?!\()", repl, t))


def load_index():
    return json.loads(INDEX.read_text()) if INDEX.exists() else []


def save_note(meta, body):
    NOTES.mkdir(exist_ok=True)
    words = len(body.split())
    meta = {**meta, "words": words, "read_mins": max(1, round(words / 230)),
            "created": datetime.now().isoformat(timespec="seconds")}
    (NOTES / f"{meta['id']}.md").write_text(body)
    with LOCK:
        index = [n for n in load_index() if n["id"] != meta["id"]]
        index.insert(0, meta)
        INDEX.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    return meta


def detect_kind(meta, extra, transcript, model):
    about = "\n\n".join(part for part in [
        f"Title: {meta['title']}\nChannel: {meta['channel']}\nLength: {ytlearn.fmt_duration(meta['secs'])}",
        "Description:\n" + extra["description"][:3000],
        "Chapters:\n" + "\n".join(t for _, t in extra["chapters"]) if extra["chapters"] else "",
        "Start of the transcript:\n" + transcript[:4000],
    ] if part)
    out = llm.run(KIND_PROMPT, model, about, timeout=180)
    words = re.findall(r"[a-z]+", out.stdout.lower()) if out.returncode == 0 else []
    return next((w for w in reversed(words) if w in KINDS), "conversation")


def to_secs(text):
    secs = 0
    for part in text.split(":"):
        secs = secs * 60 + int(part)
    return secs


def download_video(vid, workdir):
    out = subprocess.run(["yt-dlp", "-f", "bv*[height<=720][vcodec^=avc1]/bv*[height<=720]/b[height<=720]/b", "--quiet",
                    "--no-warnings", "--no-playlist", "-o", str(Path(workdir) / "video.%(ext)s"),
                    f"https://www.youtube.com/watch?v={vid}"], capture_output=True, text=True, timeout=1800)
    video = next((f for f in Path(workdir).glob("video.*") if not f.name.endswith(".part")), None)
    if video and video.stat().st_size:
        return video, ""
    errors = [l for l in out.stderr.splitlines() if "ERROR" in l]
    return None, (errors or out.stderr.strip().splitlines() or ["no output"])[-1][:200]


THUMB = (32, 18)


def tiny_frame(video, t):
    """A 32x18 grayscale copy of the frame at t seconds, as bytes, for comparing frames cheaply."""
    out = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                          "-vf", f"scale={THUMB[0]}:{THUMB[1]},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, timeout=60)
    return out.stdout if len(out.stdout) == THUMB[0] * THUMB[1] else None


def frame_diff(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def pick_frames(video, spans, per_step=6):
    """Choose one moment in each (start, end) span that best shows what is on screen.

    Tutorials cut back to the same shot again and again, usually the presenter talking to the camera.
    So for each step, take a few candidate frames and keep the one that looks least like the candidates
    of the other steps. Blank frames (fades, black screens) are skipped."""
    cands = []
    for i, (t0, t1) in enumerate(spans):
        span = max(2, t1 - t0)
        for k in range(per_step):
            t = t0 + span * (0.1 + 0.8 * k / max(1, per_step - 1))
            img = tiny_frame(video, t)
            if img:
                mean = sum(img) / len(img)
                if (sum((x - mean) ** 2 for x in img) / len(img)) ** 0.5 >= 12:
                    cands.append((i, t, img))
    picks = {}
    for i, t, img in cands:
        others = sorted(frame_diff(img, o) for j, _, o in cands if j != i)
        score = sum(others[:3]) / len(others[:3]) if others else 0
        if score > picks.get(i, (-1, 0))[0]:
            picks[i] = (score, t)
    return [picks[i][1] if i in picks else t0 + min(5, (t1 - t0) / 4) for i, (t0, t1) in enumerate(spans)]


def add_frames(vid, md, total, log=print):
    """Put a frame from the video under each numbered step, linked to that moment in the video.
    Returns the new markdown and an error message, which is empty when the frames worked."""
    steps = list(re.finditer(r"^### (\d+)\..*\[(\d{1,2}(?::\d{2}){1,2})\]\s*$", md, re.M))
    if not steps:
        return md, ""
    log(f"Downloading the video for screenshots ({len(steps)} steps)…")
    out_dir = FRAMES / vid
    starts = [to_secs(m.group(2)) for m in steps]
    spans = [(t0, starts[i + 1] if i + 1 < len(starts) and starts[i + 1] > t0 else (total or t0 + 30))
             for i, t0 in enumerate(starts)]
    with tempfile.TemporaryDirectory() as workdir:
        video, error = download_video(vid, workdir)
        if not video:
            log(f"No screenshots: the video download failed ({error})")
            return md, f"The video download failed, so this note has no screenshots. yt-dlp said: {error}"
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("*.jpg"):
            old.unlink()
        log("Choosing screenshots…")
        times = pick_frames(video, spans)
        for m, t in zip(steps, times):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                            "-vf", "scale='min(1280,iw)':-2", "-q:v", "4", str(out_dir / f"{m.group(1)}.jpg")],
                           capture_output=True, timeout=120)
    parts, last = [], 0
    for m, t in zip(steps, times):
        if (out_dir / f"{m.group(1)}.jpg").exists():
            parts += [md[last:m.end()], f"\n\n[![Step {m.group(1)} at {stamp(t)}](/frames/{vid}/{m.group(1)}.jpg)]"
                                        f"(https://youtu.be/{vid}?t={int(t)})"]
            last = m.end()
    return "".join(parts) + md[last:], ""


def links_section(urls):
    items = []
    for url in urls:
        p = urllib.parse.urlparse(url)
        host = (p.hostname or "").removeprefix("www.")
        segs = [x for x in p.path.split("/") if x]
        if host == "github.com" and len(segs) >= 2:
            label = f"GitHub: {segs[0]}/{segs[1]}"
        else:
            label = host + ("/" + "/".join(segs) if segs else "")
        items.append(f"- [{label}]({url})")
    return "## Links\nFrom the video description.\n" + "\n".join(items) if items else ""


def make_notes(vid, model, log=print, kind=None):
    existing = next((n for n in load_index() if n["id"] == vid), None)
    if existing and (NOTES / f"{vid}.md").exists():
        log(f"Already have notes for {existing['title']}")
        return existing
    with tempfile.TemporaryDirectory() as workdir:
        meta, transcript, extra = None, None, None
        for wait in (0, 5, 20, 45):
            time.sleep(wait)
            meta, transcript, extra = fetch(vid, workdir)
            if transcript:
                break
    if not transcript:
        raise RuntimeError(f"No English or Burmese transcript available for {vid}")
    if kind not in KINDS:
        log(f"Checking what kind of video this is: {meta['title']}")
        kind = detect_kind(meta, extra, transcript,
                           llm.model_for_language(meta.get("language", "en"), model))
    meta["kind"] = kind
    blocks = []
    if extra["chapters"]:
        blocks.append("## Chapters\n" + "\n".join(f"[{stamp(t)}] {title}" for t, title in extra["chapters"]))
    fmt = {"title": meta["title"], "channel": meta["channel"], "duration": ytlearn.fmt_duration(meta["secs"])}
    if kind == "tutorial":
        found, used = context.gather(context.links(extra["description"]), log)
        if found:
            blocks.append("## Linked sources\n" + found)
            meta["sources"] = used
        prompt = notes_prompt(kind, meta.get("language", "en")).format(**fmt, published=meta.get("published", "date unknown"))
        heading = "## Goal"
    else:
        prompt = notes_prompt(kind, meta.get("language", "en")).format(**fmt)
        if extra["chapters"]:
            prompt += "\nThe video's own chapters come before the transcript on stdin. Use them to group the key ideas."
        heading = "## TL;DR"
    log(f"Writing {kind} notes: {meta['title']}")
    stdin = "\n\n".join(blocks + ["## Transcript\n" + transcript]) if blocks else transcript
    source = stdin[:400000]
    out = llm.run_burmese(prompt, model, source, source) if meta.get("language") == "my" \
        else llm.run(prompt, model, source)
    body = out.stdout.strip()
    if out.returncode != 0 or not body.startswith(heading):
        reason = (out.stderr.strip() or body).splitlines()[-1][:200] if (out.stderr.strip() or body) else "no output"
        raise RuntimeError(f"Notes failed for {meta['title']}: {reason}")
    body = clean_glossary(body)
    if kind == "tutorial":
        links = links_section(context.links(extra["description"]))
        if links:
            body = body.replace("\n## Glossary", f"\n{links}\n\n## Glossary", 1) if "\n## Glossary" in body \
                else f"{body.rstrip()}\n\n{links}\n"
        body, error = add_frames(vid, body, meta["secs"], log)
        if error:
            # Shown at the top of the note, so the reader knows why the screenshots are missing.
            notice = f"> {error} Try `brew upgrade yt-dlp`, then make the note again.\n\n"
            body = re.sub(r"^## Steps\n", lambda m: m.group(0) + notice, body, count=1, flags=re.M)
        meta["frames"] = len(list((FRAMES / vid).glob("*.jpg"))) if (FRAMES / vid).exists() else 0
    return save_note(meta, link_stamps(body, vid))


def make_article_notes(url, model, log=print):
    article_id = "a" + hashlib.sha256(url.encode()).hexdigest()[:10]
    existing = next((n for n in load_index() if n["id"] == article_id), None)
    if existing and (NOTES / f"{article_id}.md").exists():
        return existing
    log(f"Reading article: {url}")
    page = context.page_text(context.get(url))
    if len(page.strip()) < 200:
        raise RuntimeError("Could not extract enough article text")
    lines = page.splitlines()
    title = lines[0].strip()[:300] or url
    article = "\n".join(lines[1:]).strip()
    language = article_language(article)
    host = urlparse(url).hostname or url
    prompt = f'''Turn the article on stdin into useful notes for someone who wants its main ideas without rereading it.

Article: "{title}" ({host})

Write markdown in exactly this structure:

## TL;DR
One sentence.

## Key ideas
3 to 7 concrete, useful takeaways.

## Action items
Concrete things to do, as "- [ ] ..." checkboxes. Omit if there are none.

{GLOSSARY_SECTION.format(language="Burmese" if language == "my" else "English")}

Use only information in the article, except glossary definitions. Output only the notes.'''
    prompt += "\n\n" + output_language_rules(language)
    source = article[:400000]
    out = llm.run_burmese(prompt, model, source, source) if language == "my" else llm.run(prompt, model, source)
    result = out.stdout.strip()
    if out.returncode != 0 or not result.startswith("## TL;DR"):
        reason = (out.stderr.strip() or result).splitlines()[-1][:200] if (out.stderr.strip() or result) else "no output"
        raise RuntimeError(f"Article notes failed: {reason}")
    meta = {"id": article_id, "title": title, "channel": host.removeprefix("www."), "url": url,
            "secs": 0, "language": language, "kind": "article"}
    return save_note(meta, result)


def article_language(text):
    return "my" if sum("MYANMAR" in unicodedata.name(c, "") for c in text) > 10 else "en"


def update_meta(vid, **fields):
    with LOCK:
        index = load_index()
        for n in index:
            if n["id"] == vid:
                n.update(fields)
        INDEX.write_text(json.dumps(index, indent=2, ensure_ascii=False))


def speakable(meta, md):
    paras = [re.sub(r"\s*[|–—]\s*", ". ", meta["title"]) + f". By {meta['channel']}."]
    md = re.sub(r"^```.*?^```[^\n]*$", "", md, flags=re.S | re.M)
    md = re.sub(r"^## Links\n.*?(?=^## |\Z)", "", md, flags=re.S | re.M)
    for line in md.splitlines():
        if line.startswith(("_Reconstructed from the transcript", "![", "[![", "> The video download failed")):
            continue
        line = re.sub(r"\s*\[\d{1,2}(?::\d{2}){1,2}\]\([^)]*\)", "", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line).strip()
        if not line:
            continue
        h2 = re.fullmatch(r"##\s+(.+)", line)
        if h2:
            paras.append(SECTION_INTROS.get(h2.group(1).strip().lower(), h2.group(1).strip() + "."))
            continue
        line = re.sub(r"^#{3,}\s+", "", line)
        line = re.sub(r"^(?:[-*+]|\d+\.)\s+(?:\[[ xX]\]\s+)?", "", line)
        line = re.sub(r"[*_`>#|]", "", line)
        line = re.sub(r"\s*/\s*(month|mo|year|yr|week|day|hour|user|seat)\b", r" per \1", line)
        for a, b in (("→", " to "), ("&", " and "), ("~", "about "), (" vs ", " versus "), ("/", " or ")):
            line = line.replace(a, b)
        line = re.sub(r"\s+", " ", line).strip()
        if line and not re.search(r"[.!?:;\"”)]$", line):
            line += "."
        if line:
            paras.append(line)
    return "\n\n".join(paras)


def make_audio(vid, voice, log=print):
    meta = next((n for n in load_index() if n["id"] == vid), None)
    if not meta:
        raise RuntimeError("Note not found")
    if meta.get("language") == "my":
        raise RuntimeError("Burmese audio is not supported yet")
    if meta.get("audio", {}).get("voice") == voice and (NOTES / f"{vid}.m4a").exists():
        return meta
    log("Waiting for the voice engine…")
    with TTS_LOCK, tempfile.TemporaryDirectory() as workdir:
        txt, wav = Path(workdir) / "script.txt", Path(workdir) / "audio.wav"
        txt.write_text(speakable(meta, (NOTES / f"{vid}.md").read_text()))
        log("Loading Kokoro…")
        proc = subprocess.Popen(["uv", "run", "--quiet", str(ROOT / "tts.py"), str(txt), str(wav), "--voice", voice],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        secs = 0
        for line in proc.stdout:
            if line.startswith("progress"):
                log(f"Recording audio… {round(float(line.split()[1]) * 100)}%")
            elif line.startswith("secs"):
                secs = float(line.split()[1])
        err = proc.stderr.read()
        if proc.wait() != 0 or not wav.exists():
            raise RuntimeError("Audio failed: " + err.strip().splitlines()[-1][:200] if err.strip() else "Audio failed")
        log("Compressing audio…")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "aac", "-b:a", "64k",
                        "-ac", "1", str(NOTES / f"{vid}.m4a")], check=True)
    update_meta(vid, audio={"voice": voice, "secs": round(secs)})
    return next(n for n in load_index() if n["id"] == vid)


def delete_note(vid):
    with LOCK:
        index = load_index()
        found = any(n["id"] == vid for n in index) or (NOTES / f"{vid}.md").exists()
        if not found:
            return False
        INDEX.write_text(json.dumps([n for n in index if n["id"] != vid], indent=2, ensure_ascii=False))
        cols = load_collections()
        for c in cols:
            if any(v["id"] == vid for v in c["videos"]):
                c.setdefault("skipped", {})[vid] = "Notes deleted"
        if cols:
            COLLECTIONS.write_text(json.dumps(cols, indent=2, ensure_ascii=False))
    for ext in ("md", "m4a"):
        (NOTES / f"{vid}.{ext}").unlink(missing_ok=True)
    return True


def run_audio_job(job, vid, voice):
    try:
        make_audio(vid, voice, lambda m: job.update(message=m))
        job.update(status="done", ids=[vid], message="Audio ready")
    except Exception as e:
        job.update(status="error", message=str(e))


def add_glossary(vid, model):
    path = NOTES / f"{vid}.md"
    md = path.read_text()
    if re.search(r"^## Glossary", md, re.M):
        return False
    language = next((n.get("language", "en") for n in load_index() if n["id"] == vid), "en")
    out = llm.run_burmese(glossary_prompt(language), model, md, md, timeout=300) if language == "my" \
        else llm.run(glossary_prompt(language), model, md, timeout=300)
    out = out.stdout.strip() if out.returncode == 0 else ""
    if not out.startswith("## Glossary"):
        return False
    out = clean_glossary(out)
    path.write_text(md.rstrip() + "\n\n" + out + "\n")
    with LOCK:
        index = load_index()
        for n in index:
            if n["id"] == vid:
                n.pop("audio", None)
                n["words"] = len(path.read_text().split())
                n["read_mins"] = max(1, round(n["words"] / 230))
        INDEX.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    return True


def load_collections():
    return json.loads(COLLECTIONS.read_text()) if COLLECTIONS.exists() else []


def save_collection(c):
    NOTES.mkdir(exist_ok=True)
    with LOCK:
        cols = [x for x in load_collections() if x["id"] != c["id"]]
        cols.insert(0, c)
        COLLECTIONS.write_text(json.dumps(cols, indent=2, ensure_ascii=False))


def tldr(md):
    m = re.search(r"^## (?:TL;DR|Goal)\s*\n(.+?)(?=^## |\Z)", md, re.S | re.M)
    return re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", m.group(1)).strip() if m else ""


def collection_view(c):
    notes = {n["id"]: n for n in load_index()}
    items = []
    for v in c["videos"]:
        n = notes.get(v["id"])
        if n and (NOTES / f"{v['id']}.md").exists():
            items.append({**n, "status": "ready", "tldr": tldr((NOTES / f"{v['id']}.md").read_text())})
        elif v["id"] in c.get("skipped", {}):
            items.append({**v, "status": "skipped", "reason": c["skipped"][v["id"]]})
        else:
            items.append({**v, "status": "pending"})
    return {**c, "items": items}


def collection_summary(c):
    notes = {n["id"]: n for n in load_index()}
    ready = [notes[v["id"]] for v in c["videos"] if v["id"] in notes]
    videos = []
    for v in c["videos"]:
        item = {"id": v["id"], "title": v["title"]}
        if v["id"] in notes:
            item.update(channel=notes[v["id"]]["channel"], read_mins=notes[v["id"]]["read_mins"])
        videos.append(item)
    return {k: c[k] for k in ("id", "kind", "title", "channel", "created")} | {
        "count": len(c["videos"]), "ready": len(ready),
        "secs": sum(v.get("secs") or 0 for v in c["videos"]),
        "read_mins": sum(n["read_mins"] for n in ready),
        "videos": videos,
    }


def note_collections(vid):
    out = []
    for c in load_collections():
        ids = [v["id"] for v in c["videos"]]
        if vid in ids:
            i = ids.index(vid)
            near = lambda j: {"id": c["videos"][j]["id"], "title": c["videos"][j]["title"]} if 0 <= j < len(ids) else None
            out.append({"id": c["id"], "title": c["title"], "kind": c["kind"], "index": i + 1, "count": len(ids),
                        "prev": near(i - 1), "next": near(i + 1)})
    return out


def parse_input(text):
    urls = re.findall(r"https?://\S+|(?:www\.)?(?:youtube\.com|youtu\.be)/\S+", text)
    videos, playlists, articles = [], [], []
    for u in urls:
        parsed = urllib.parse.urlparse(u if u.startswith("http") else "https://" + u)
        lst = urllib.parse.parse_qs(parsed.query).get("list", [""])[0]
        if parsed.path.rstrip("/") == "/playlist" and lst and not lst.startswith(SKIP_LISTS):
            playlists.append(lst)
        elif video_id(u):
            videos.append(video_id(u))
        elif parsed.scheme in ("http", "https") and parsed.hostname:
            articles.append(u.rstrip(".,;!"))
    if urls:
        if not videos and not playlists and not articles:
            raise RuntimeError("No supported links found")
        return videos, playlists, articles, ""
    if video_id(text):
        return [video_id(text)], [], [], ""
    return [], [], [], text.strip()


def expand_playlist(pid):
    out = subprocess.run(["yt-dlp", "--flat-playlist", "-J", "--no-warnings", f"https://www.youtube.com/playlist?list={pid}"],
                         capture_output=True, text=True, timeout=180)
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Could not read playlist {pid}. It can be private or deleted.")
    entries = [e for e in data.get("entries") or [] if e and e.get("id") and e.get("title") not in ("[Private video]", "[Deleted video]")]
    return {
        "id": pid, "kind": "playlist", "title": data.get("title") or pid,
        "channel": data.get("channel") or data.get("uploader") or "",
        "url": f"https://www.youtube.com/playlist?list={pid}", "total": len(entries),
        "videos": [{"id": e["id"], "title": e.get("title") or e["id"], "secs": int(e.get("duration") or 0)} for e in entries[:MAX_PLAYLIST]],
        "created": datetime.now().isoformat(timespec="seconds"),
    }


def topic_videos(topic, minutes, model):
    budget = minutes * 60
    pool = ytlearn.candidates(topic, budget, 10000, 90 * 60)
    return ytlearn.rank(topic, pool, budget, 1, model) if pool else []


def run_job(job, text, minutes, model, kind=None):
    def log(msg):
        job["message"] = msg

    try:
        videos, playlists, articles, topic = parse_input(text)
        collections = []
        if topic:
            log(f"Finding the best videos on “{topic}”…")
            picks = topic_videos(topic, minutes, model)
            if not picks:
                raise RuntimeError("No good videos found for that topic")
            collections.append({
                "id": "t-" + re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:60], "kind": "topic", "title": topic,
                "channel": "", "url": "", "total": len(picks),
                "videos": [{"id": v["id"], "title": v["title"], "secs": v["secs"]} for v in picks],
                "created": datetime.now().isoformat(timespec="seconds"),
            })
        for pid in playlists:
            log("Reading the playlist…")
            collections.append(expand_playlist(pid))
        for c in collections:
            save_collection(c)
        vids = list(dict.fromkeys(videos + [v["id"] for c in collections for v in c["videos"]]))
        if not vids and not articles:
            raise RuntimeError("The playlist has no public videos")
        work = [("video", v) for v in vids] + [("article", u) for u in dict.fromkeys(articles)]
        title = collections[0]["title"] if len(collections) == 1 and not videos and not articles else (f"{len(work)} sources" if len(work) > 1 else None)
        job.update(collections=[c["id"] for c in collections], title=title, total=len(work), done=0)
        log(f"Reading {len(work)} source{'s' if len(work) != 1 else ''}…")
        done, errors = [], {}

        def one(item):
            source_type, value = item
            try:
                note = make_article_notes(value, model, log if len(work) == 1 else (lambda m: None)) if source_type == "article" \
                    else make_notes(value, model, log if len(work) == 1 else (lambda m: None), kind)
                done.append(note["id"])
            except Exception as e:
                errors[value] = str(e)
            finished = len(done) + len(errors)
            job.update(ids=list(done), done=finished)
            if len(work) > 1:
                log(f"{finished} of {len(work)} done")

        with ThreadPoolExecutor(3) as ex:
            list(ex.map(one, work))
        for c in collections:
            c["skipped"] = {v["id"]: errors[v["id"]] for v in c["videos"] if v["id"] in errors}
            save_collection(c)
        msg = f"{len(done)} note{'s' if len(done) != 1 else ''} ready"
        if errors:
            msg += f" · {len(errors)} skipped: " + "; ".join(dict.fromkeys(errors.values()))
        job.update(status="done" if done else "error", ids=done, message=msg if done else "; ".join(dict.fromkeys(errors.values())))
    except Exception as e:
        job.update(status="error", message=str(e))


def start_daily(model):
    """Start building today's watch list, or return the build that is already running."""
    with LOCK:
        if DAILY_JOB.get("status") == "running":
            return DAILY_JOB
        DAILY_JOB.clear()
        DAILY_JOB.update(id=uuid.uuid4().hex[:12], status="running", message="Starting…", ids=[])
        JOBS[DAILY_JOB["id"]] = DAILY_JOB
    threading.Thread(target=run_daily_job, args=(DAILY_JOB, model), daemon=True).start()
    return DAILY_JOB


def run_daily_job(job, model):
    try:
        data = daily.build(DAILY, load_index(), model, log=lambda m: job.update(message=m))
        job.update(status="done", message=f"{len(data['picks'])} picks from {data['considered']} new videos")
    except Exception as e:
        job.update(status="error", message=str(e))


def auto_daily(model):
    """Make today's list once a day while the server runs, so it is ready when you open the app."""
    while True:
        if DAILY.sources() and not DAILY.list_for(datetime.now().date().isoformat()):
            start_daily(model)
        time.sleep(15 * 60)


def daily_view():
    today = datetime.now().date().isoformat()
    data = DAILY.list_for(today) or DAILY.latest() or {"date": None, "picks": [], "considered": 0}
    return {**daily.view(data, load_index()), "today": today, "sources": DAILY.sources(),
            "job": DAILY_JOB if DAILY_JOB.get("status") == "running" else None}


class Handler(BaseHTTPRequestHandler):
    model = None

    def log_message(self, *args):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path, ctype):
        size = path.stat().st_size
        start, end = 0, size - 1
        rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if rng and rng.group(1):
            start = int(rng.group(1))
            end = min(int(rng.group(2)), size - 1) if rng.group(2) else end
        elif rng and rng.group(2):
            start = max(0, size - int(rng.group(2)))
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as f:
            f.seek(start)
            try:
                self.wfile.write(f.read(end - start + 1))
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_GET(self):
        self.path = urlparse(self.path).path
        if self.path == "/api/voices":
            return self.send(200, [{"id": v, "label": label} for v, label in VOICES])
        m = re.fullmatch(r"/audio/([\w-]{11})\.m4a", self.path)
        if m:
            f = NOTES / f"{m.group(1)}.m4a"
            return self.send_file(f, "audio/mp4") if f.exists() else self.send(404, {"error": "not found"})
        m = re.fullmatch(r"/frames/([\w-]{11})/(\d+)\.jpg", self.path)
        if m:
            f = FRAMES / m.group(1) / f"{m.group(2)}.jpg"
            return self.send(200, f.read_bytes(), "image/jpeg") if f.exists() else self.send(404, {"error": "not found"})
        if self.path == "/manifest.webmanifest":
            return self.send(200, (ROOT / "manifest.webmanifest").read_bytes(), "application/manifest+json")
        if self.path == "/favicon.ico":
            self.path = "/assets/favicon.ico"
        m = re.fullmatch(r"/assets/([\w-]+\.(svg|png|ico))", self.path)
        if m:
            f = ROOT / "assets" / m.group(1)
            ctype = {"svg": "image/svg+xml", "png": "image/png", "ico": "image/x-icon"}[m.group(2)]
            return self.send(200, f.read_bytes(), ctype) if f.exists() else self.send(404, {"error": "not found"})
        if self.path == "/":
            return self.send(200, (ROOT / "ytnotes.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/notes":
            return self.send(200, load_index())
        m = re.fullmatch(r"/api/notes/([\w-]{11})", self.path)
        if m:
            meta = next((n for n in load_index() if n["id"] == m.group(1)), None)
            if not meta:
                return self.send(404, {"error": "not found"})
            return self.send(200, {**meta, "markdown": (NOTES / f"{meta['id']}.md").read_text(),
                                   "collections": note_collections(meta["id"])})
        if self.path == "/api/daily":
            return self.send(200, daily_view())
        if self.path == "/api/collections":
            return self.send(200, [collection_summary(c) for c in load_collections()])
        m = re.fullmatch(r"/api/collections/([\w-]+)", self.path)
        if m:
            c = next((c for c in load_collections() if c["id"] == m.group(1)), None)
            return self.send(200, collection_view(c)) if c else self.send(404, {"error": "not found"})
        if self.path == "/api/jobs":
            return self.send(200, [j for j in list(JOBS.values()) if j.get("input") and j["status"] == "running"])
        m = re.fullmatch(r"/api/jobs/(\w+)", self.path)
        if m and m.group(1) in JOBS:
            return self.send(200, JOBS[m.group(1)])
        self.send(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        m = re.fullmatch(r"/api/audio/([\w-]{11})", self.path)
        if m:
            voice = body.get("voice") if body.get("voice") in dict(VOICES) else VOICES[0][0]
            job_id = uuid.uuid4().hex[:12]
            JOBS[job_id] = {"id": job_id, "status": "running", "message": "Starting…", "ids": []}
            threading.Thread(target=run_audio_job, args=(JOBS[job_id], m.group(1), voice), daemon=True).start()
            return self.send(202, JOBS[job_id])
        if self.path == "/api/daily":
            return self.send(202, start_daily(self.model))
        if self.path == "/api/sources":
            try:
                if body.get("seed"):
                    daily.seed(DAILY, load_index())
                else:
                    DAILY.add(daily.resolve(body.get("input") or ""))
            except Exception as e:
                return self.send(400, {"error": str(e)})
            return self.send(200, DAILY.sources())
        if self.path != "/api/jobs":
            return self.send(404, {"error": "not found"})
        text = (body.get("input") or "").strip()
        if not text:
            return self.send(400, {"error": "Paste a YouTube or article link, or type a topic"})
        job_id = uuid.uuid4().hex[:12]
        JOBS[job_id] = {"id": job_id, "status": "running", "message": "Starting…", "ids": [], "collections": [],
                        "title": None, "total": 0, "done": 0, "input": text, "label": body.get("label") or text,
                        "vid": body.get("vid")}
        threading.Thread(target=run_job, args=(JOBS[job_id], text, int(body.get("minutes") or 60), self.model,
                                               body.get("kind")), daemon=True).start()
        self.send(202, JOBS[job_id])

    def do_DELETE(self):
        m = re.fullmatch(r"/api/sources/(UC[\w-]{22})", urlparse(self.path).path)
        if m:
            return self.send(200, DAILY.sources()) if DAILY.remove(m.group(1)) else self.send(404, {"error": "not found"})
        m = re.fullmatch(r"/api/notes/([\w-]{11})", urlparse(self.path).path)
        if not m:
            return self.send(404, {"error": "not found"})
        if not delete_note(m.group(1)):
            return self.send(404, {"error": "Note not found"})
        self.send(200, {"id": m.group(1), "deleted": True})


def lan_ip():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("10.255.255.255", 1))
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main():
    ap = argparse.ArgumentParser(description="Read YouTube videos instead of watching them.")
    ap.add_argument("input", nargs="*", help="YouTube links, playlist links, or a topic; omit to open the app")
    ap.add_argument("-t", "--time", type=int, default=60, help="minutes of video to cover for a topic")
    ap.add_argument("--model", default=None,
                    help=f"Gemini model (agy), pi model as provider/model (default: English {DEFAULT_MODEL}, Burmese {llm.BURMESE_MODEL}; explicit choice applies to both), or a Claude model such as claude-haiku-5-5")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true", help="don't open the browser")
    ap.add_argument("--lan", action="store_true", help="also serve on your local network, e.g. for your phone")
    ap.add_argument("--audio", action="store_true", help="also record an audio version with Kokoro")
    ap.add_argument("--voice", default=VOICES[0][0], choices=[v for v, _ in VOICES])
    ap.add_argument("--kind", choices=["auto", *KINDS], default="auto",
                    help="note structure to use; auto detects it from the video (default)")
    ap.add_argument("--daily", action="store_true",
                    help="make today's watch list from your channels; adds the channels of your notes the first time")
    ap.add_argument("--add-glossary", action="store_true", help="add a glossary to existing notes that lack one")
    args = ap.parse_args()

    if args.add_glossary:
        notes = load_index()
        with ThreadPoolExecutor(3) as ex:
            added = list(ex.map(lambda n: add_glossary(n["id"], args.model), notes))
        for n, ok in zip(notes, added):
            print(f"{'added  ' if ok else 'skipped'} {n['title']}")
        return

    if args.daily:
        if not DAILY.sources():
            print(f"Added {daily.seed(DAILY, load_index())} channels from your notes", file=sys.stderr)
        data = daily.build(DAILY, load_index(), args.model, log=lambda m: print(m, file=sys.stderr))
        print(f"Worth watching · {data['date']} · {len(data['picks'])} of {data['considered']} new videos")
        for i, p in enumerate(data["picks"], 1):
            length = f" · {ytlearn.fmt_duration(p['secs'])}" if p.get("secs") else ""
            print(f"\n{i}. {p['title']}\n   {p['channel']}{length} · https://youtu.be/{p['id']}\n   {p['why']}")
        if data.get("error"):
            print(data["error"], file=sys.stderr)
        return

    if args.input:
        job = {"status": "running", "message": "", "ids": []}
        run_job(job, "\n".join(args.input), args.time, args.model, args.kind)
        if job["status"] == "error":
            sys.exit(job["message"])
        for vid in job["ids"]:
            print(NOTES / f"{vid}.md")
            if args.audio:
                make_audio(vid, args.voice, lambda m: print(f"\r{m:<40}", end="", file=sys.stderr, flush=True))
                print(f"\r{NOTES / f'{vid}.m4a'}{' ' * 20}")
        if job["message"] and "ready" not in job["message"]:
            print(job["message"], file=sys.stderr)
        return

    Handler.model = args.model
    threading.Thread(target=auto_daily, args=(args.model,), daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0" if args.lan else "127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"EasyNotes running at {url}  (Ctrl+C to stop)")
    if args.lan:
        print(f"On your phone (same Wi-Fi): http://{lan_ip()}:{args.port}")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
