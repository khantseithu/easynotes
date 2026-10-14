#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import ytlearn

ROOT = Path(__file__).resolve().parent
NOTES = ROOT / "notes"
INDEX = NOTES / "index.json"
DEFAULT_MODEL = "claude-haiku-5-5"
LOCK = threading.Lock()
TTS_LOCK = threading.Lock()
JOBS = {}
VOICES = [
    ("af_heart", "Heart · US female"), ("af_bella", "Bella · US female"),
    ("am_michael", "Michael · US male"), ("am_fenrir", "Fenrir · US male"),
    ("bf_emma", "Emma · UK female"), ("bm_george", "George · UK male"),
]
SECTION_INTROS = {"tl;dr": "In short.", "key ideas": "Key ideas.", "frameworks": "Frameworks.",
                  "quotes": "A few memorable quotes.", "action items": "Action items.", "glossary": "Glossary."}

NOTES_PROMPT = """Turn the YouTube transcript on stdin into notes good enough that the reader does not need to watch the video.

Video: "{title}" by {channel} ({duration})

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

## Glossary
Every abbreviation and acronym used anywhere in the notes above (e.g. LTV, CAC, ARR, ICP, PLG), plus industry jargon
a smart newcomer to the field would not know (e.g. churn, payback period). Skip everyday words, product names and analogies entirely: never list a skipped term or comment on what you skipped.
Sort alphabetically, as "- **TERM** (full name, if it is an abbreviation): one plain-English sentence explaining it, in the context of this video."
Omit this section only if the notes use no such terms.

Length should match the substance: about 300 words for a 10-minute video, up to about 1500 for a long interview.
Use only what is in the transcript, except glossary definitions, which may use general knowledge. Timestamps must come from the [mm:ss] markers in the transcript.
Output only the notes."""

GLOSSARY_PROMPT = """The notes on stdin were written from a YouTube video. Write a glossary for them.

## Glossary
Every abbreviation and acronym used anywhere in the notes above (e.g. LTV, CAC, ARR, ICP, PLG), plus industry jargon
a smart newcomer to the field would not know (e.g. churn, payback period). Skip everyday words, product names and analogies entirely: never list a skipped term or comment on what you skipped.
Sort alphabetically, as "- **TERM** (full name, if it is an abbreviation): one plain-English sentence explaining it, in the context of this video."
Omit this section only if the notes use no such terms.

Output only the "## Glossary" section, or nothing if there are no such terms."""


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


def api_transcript(vid):
    out = subprocess.run(["uvx", "-q", "--from", "youtube-transcript-api==1.2.4", "youtube_transcript_api", vid,
                          "--languages", "en", "--format", "json"], capture_output=True, text=True, timeout=180)
    try:
        return [(c["start"], c["text"]) for c in json.loads(out.stdout)[0]]
    except (json.JSONDecodeError, IndexError, KeyError, TypeError):
        return []


def fetch(vid, workdir, langs):
    subprocess.run(
        ["yt-dlp", "--skip-download", "--write-info-json", "--write-auto-subs", "--write-subs",
         "--sub-langs", langs, "--sub-format", "json3", "--quiet", "--no-warnings",
         "-o", str(Path(workdir) / "%(id)s"), f"https://www.youtube.com/watch?v={vid}"],
        capture_output=True, timeout=180,
    )
    info_file = Path(workdir) / f"{vid}.info.json"
    subs = sorted(Path(workdir).glob(f"{vid}*.json3"))
    info = json.loads(info_file.read_text()) if info_file.exists() else video_info(vid)
    if not info:
        return None, None
    if subs:
        segments = []
        for e in json.loads(subs[0].read_text()).get("events", []):
            segments.append((e.get("tStartMs", 0) / 1000, "".join(s.get("utf8", "") for s in e.get("segs", []))))
    else:
        segments = api_transcript(vid)
    if not segments:
        return None, None
    meta = {
        "id": vid,
        "title": info.get("title", vid),
        "channel": info.get("channel") or info.get("uploader", ""),
        "secs": info.get("duration") or 0,
    }
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
    return meta, "\n".join(lines)


def clean_glossary(md):
    return "\n".join(l for l in md.splitlines() if not re.search(r"\(\s*[^)]*\bomit", l, re.I))


def link_stamps(md, vid):
    def repl(m):
        parts = [int(p) for p in m.group(1).split(":")]
        secs = 0
        for p in parts:
            secs = secs * 60 + p
        return f"[{m.group(1)}](https://youtu.be/{vid}?t={secs})"
    return re.sub(r"\[(\d{1,2}(?::\d{2}){1,2})\](?!\()", repl, md)


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


def make_notes(vid, model, log=print):
    existing = next((n for n in load_index() if n["id"] == vid), None)
    if existing and (NOTES / f"{vid}.md").exists():
        log(f"Already have notes for {existing['title']}")
        return existing
    with tempfile.TemporaryDirectory() as workdir:
        meta, transcript = None, None
        for wait, langs in [(0, "en"), (5, "en.*"), (20, "en"), (45, "en.*")]:
            time.sleep(wait)
            meta, transcript = fetch(vid, workdir, langs)
            if transcript:
                break
    if not transcript:
        raise RuntimeError(f"No English transcript available for {vid}")
    log(f"Writing notes: {meta['title']}")
    prompt = NOTES_PROMPT.format(title=meta["title"], channel=meta["channel"],
                                 duration=ytlearn.fmt_duration(meta["secs"])) + WRITING_RULES
    out = subprocess.run(["claude", "-p", prompt, "--model", model],
                         input=transcript[:400000], capture_output=True, text=True, timeout=900)
    body = out.stdout.strip()
    if out.returncode != 0 or not body.startswith("## TL;DR"):
        reason = (out.stderr.strip() or body).splitlines()[-1][:200] if (out.stderr.strip() or body) else "no output"
        raise RuntimeError(f"Notes failed for {meta['title']}: {reason}")
    return save_note(meta, link_stamps(clean_glossary(body), vid))


def update_meta(vid, **fields):
    with LOCK:
        index = load_index()
        for n in index:
            if n["id"] == vid:
                n.update(fields)
        INDEX.write_text(json.dumps(index, indent=2, ensure_ascii=False))


def speakable(meta, md):
    paras = [re.sub(r"\s*[|–—]\s*", ". ", meta["title"]) + f". By {meta['channel']}."]
    for line in md.splitlines():
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
    out = subprocess.run(["claude", "-p", GLOSSARY_PROMPT + WRITING_RULES, "--model", model],
                         input=md, capture_output=True, text=True, timeout=300)
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


def topic_videos(topic, minutes, model):
    budget = minutes * 60
    pool = ytlearn.candidates(topic, budget, 10000, 90 * 60)
    return ytlearn.rank(topic, pool, budget, 1, model) if pool else []


def run_job(job, text, minutes, model):
    def log(msg):
        job["message"] = msg

    try:
        vid = video_id(text)
        if vid:
            vids = [vid]
        else:
            log(f"Finding the best videos on “{text}”…")
            vids = [v["id"] for v in topic_videos(text, minutes, model)]
            if not vids:
                raise RuntimeError("No good videos found for that topic")
        log(f"Reading {len(vids)} video{'s' if len(vids) > 1 else ''}…")
        done, errors = [], []

        def one(v):
            try:
                done.append(make_notes(v, model, log)["id"])
                log(f"Done {len(done)} of {len(vids)}")
            except Exception as e:
                errors.append(str(e))

        with ThreadPoolExecutor(2) as ex:
            list(ex.map(one, vids))
        msg = f"{len(done)} note{'s' if len(done) != 1 else ''} ready"
        if errors:
            msg += f" · {len(errors)} skipped: " + "; ".join(errors)
        job.update(status="done" if done else "error", ids=done, message=msg if done else "; ".join(errors))
    except Exception as e:
        job.update(status="error", message=str(e))


class Handler(BaseHTTPRequestHandler):
    model = DEFAULT_MODEL

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
        if self.path == "/manifest.webmanifest":
            return self.send(200, (ROOT / "manifest.webmanifest").read_bytes(), "application/manifest+json")
        m = re.fullmatch(r"/assets/([\w-]+\.(svg|png))", self.path)
        if m:
            f = ROOT / "assets" / m.group(1)
            ctype = "image/svg+xml" if m.group(2) == "svg" else "image/png"
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
            return self.send(200, {**meta, "markdown": (NOTES / f"{meta['id']}.md").read_text()})
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
        if self.path != "/api/jobs":
            return self.send(404, {"error": "not found"})
        text = (body.get("input") or "").strip()
        if not text:
            return self.send(400, {"error": "Paste a YouTube link or type a topic"})
        job_id = uuid.uuid4().hex[:12]
        JOBS[job_id] = {"id": job_id, "status": "running", "message": "Starting…", "ids": []}
        threading.Thread(target=run_job, args=(JOBS[job_id], text, int(body.get("minutes") or 60), self.model),
                         daemon=True).start()
        self.send(202, JOBS[job_id])


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
    ap.add_argument("input", nargs="?", help="YouTube URL or topic; omit to open the app")
    ap.add_argument("-t", "--time", type=int, default=60, help="minutes of video to cover for a topic")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model for notes (default {DEFAULT_MODEL})")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true", help="don't open the browser")
    ap.add_argument("--lan", action="store_true", help="also serve on your local network, e.g. for your phone")
    ap.add_argument("--audio", action="store_true", help="also record an audio version with Kokoro")
    ap.add_argument("--voice", default=VOICES[0][0], choices=[v for v, _ in VOICES])
    ap.add_argument("--add-glossary", action="store_true", help="add a glossary to existing notes that lack one")
    args = ap.parse_args()

    if args.add_glossary:
        notes = load_index()
        with ThreadPoolExecutor(3) as ex:
            added = list(ex.map(lambda n: add_glossary(n["id"], args.model), notes))
        for n, ok in zip(notes, added):
            print(f"{'added  ' if ok else 'skipped'} {n['title']}")
        return

    if args.input:
        job = {"status": "running", "message": "", "ids": []}
        run_job(job, args.input, args.time, args.model)
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
    server = ThreadingHTTPServer(("0.0.0.0" if args.lan else "127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"YT Notes running at {url}  (Ctrl+C to stop)")
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
