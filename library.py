"""Search, highlights and exports for the notes library."""
import csv
import io
import json
import re
import threading
import uuid
import zipfile
from datetime import date, datetime, timedelta

LOCK = threading.Lock()
MAX_TEXT = 2000
CARD_LINE = re.compile(r"^[\s*-]*([QA])\**\s*:\**\s*(.+?)\s*$")
GRADES = ("again", "good", "easy")
GLOSSARY_LINE = re.compile(r"^-\s+\*\*(.+?)\*\*\s*(?:\(([^)]*)\))?\s*:?\s*(.*)$")


def search(notes, read_text, query, limit=30):
    """Return the notes whose title or text contains every word of the query.

    Matches in the title come first. read_text(id) returns the markdown of a note.
    """
    words = query.lower().split()
    if not words:
        return []
    hits = []
    for n in notes:
        title = f"{n['title']} {n.get('channel') or ''}".lower()
        body = read_text(n["id"])
        low = body.lower()
        if not all(w in title or w in low for w in words):
            continue
        found = [low.find(w) for w in words if w in low]
        snippet = snippet_at(body, min(found)) if found else ""
        hits.append({"id": n["id"], "title": n["title"], "channel": n.get("channel") or "",
                     "snippet": snippet, "in_title": all(w in title for w in words)})
    hits.sort(key=lambda h: not h["in_title"])
    return [{k: v for k, v in h.items() if k != "in_title"} for h in hits[:limit]]


def snippet_at(body, pos, before=50, after=110):
    start = max(0, pos - before)
    text = body[start:pos + after]
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_#`>]+", "", text)
    text = " ".join(text.split())
    return ("… " if start else "") + text + (" …" if pos + after < len(body) else "")


def highlights_for(path, vid):
    return load(path).get(vid, [])


def load(path):
    return json.loads(path.read_text()) if path.exists() else {}


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def add_highlight(path, vid, quote, comment=""):
    quote = " ".join((quote or "").split())
    comment = (comment or "").strip()
    if not quote:
        raise ValueError("Select some text to highlight")
    if len(quote) > MAX_TEXT or len(comment) > MAX_TEXT:
        raise ValueError(f"Keep the highlight and the comment under {MAX_TEXT} characters")
    item = {"id": uuid.uuid4().hex[:8], "quote": quote, "comment": comment,
            "created": datetime.now().isoformat(timespec="seconds")}
    with LOCK:
        data = load(path)
        data[vid] = [*data.get(vid, []), item]
        save(path, data)
    return item


def delete_highlight(path, vid, hid):
    with LOCK:
        data = load(path)
        kept = [h for h in data.get(vid, []) if h["id"] != hid]
        if len(kept) == len(data.get(vid, [])):
            return False
        data[vid] = kept
        save(path, data)
    return True


def drop_highlights(path, vid):
    with LOCK:
        data = load(path)
        if data.pop(vid, None) is not None:
            save(path, data)


def parse_cards(text):
    """The (question, answer) pairs of model output written as "Q: ..." and "A: ..." lines."""
    cards, question = [], None
    for line in text.splitlines():
        m = CARD_LINE.match(line)
        if not m:
            continue
        if m.group(1) == "Q":
            question = m.group(2)
        elif question:
            cards.append((question, m.group(2)))
            question = None
    return cards


def set_cards(path, vid, pairs, today):
    cards = [{"id": uuid.uuid4().hex[:8], "q": q, "a": a, "due": today.isoformat(), "interval": 0, "ease": 2.5, "reps": 0}
             for q, a in pairs]
    with LOCK:
        data = load(path)
        data[vid] = cards
        save(path, data)
    return cards


def drop_cards(path, vid):
    drop_highlights(path, vid)


def schedule(card, grade, today):
    """Spaced repetition: each correct answer pushes the card further out, a miss brings it back today."""
    interval, ease, reps = card["interval"], card["ease"], card["reps"]
    if grade == "again":
        interval, ease, reps = 0, max(1.3, ease - 0.2), 0
    else:
        interval = 1 if reps == 0 else 3 if reps == 1 else round(interval * ease)
        if grade == "easy":
            interval, ease = max(4, round(interval * 1.3)), ease + 0.15
        reps += 1
    return {**card, "interval": interval, "ease": round(ease, 2), "reps": reps,
            "due": (today + timedelta(days=interval)).isoformat()}


def review_card(path, vid, cid, grade, today):
    if grade not in GRADES:
        raise ValueError("Grade the card as again, good or easy")
    with LOCK:
        data = load(path)
        cards = data.get(vid, [])
        i = next((i for i, c in enumerate(cards) if c["id"] == cid), None)
        if i is None:
            return None
        cards[i] = schedule(cards[i], grade, today)
        save(path, data)
    return cards[i]


def due_cards(path, notes, today, vid=None):
    """The cards due by today, oldest first, each with the note it came from, and the next date after them."""
    titles = {n["id"]: n["title"] for n in notes}
    due, later = [], []
    for note_id, cards in load(path).items():
        if note_id not in titles or vid and note_id != vid:
            continue
        for c in cards:
            if date.fromisoformat(c["due"]) <= today:
                due.append({**c, "note": note_id, "title": titles[note_id]})
            else:
                later.append(c["due"])
    due.sort(key=lambda c: c["due"])
    return {"cards": due, "next_due": min(later) if later else None}


def yaml_string(text):
    # A JSON string is also a valid YAML double-quoted scalar.
    return json.dumps(str(text), ensure_ascii=False)


def note_markdown(meta, body, highlights, source):
    """A note as a Markdown file with front matter, for Obsidian or any other editor."""
    front = ["---",
             f"title: {yaml_string(meta['title'])}",
             f"channel: {yaml_string(meta.get('channel') or '')}",
             f"source: {yaml_string(source)}",
             f"created: {yaml_string(meta.get('created') or '')}",
             "---", ""]
    text = "\n".join(front) + body.rstrip() + "\n"
    if highlights:
        parts = []
        for h in highlights:
            quote = "\n".join(f"> {line}" for line in h["quote"].splitlines() or [h["quote"]])
            parts.append(quote + (f"\n\n{h['comment']}" if h["comment"] else ""))
        text += "\n## Your highlights\n\n" + "\n\n".join(parts) + "\n"
    return text


def glossary_cards(body):
    """The (term, back) pairs of the Glossary section of a note."""
    section = re.search(r"^## Glossary[ \t]*$(.*?)(?=^## |\Z)", body, re.M | re.S)
    if not section:
        return []
    cards = []
    for line in section.group(1).splitlines():
        m = GLOSSARY_LINE.match(line.strip())
        if not m:
            continue
        term, full, definition = m.group(1).strip(), (m.group(2) or "").strip(), m.group(3).strip()
        if term and definition:
            cards.append((term, f"{full}. {definition}" if full else definition))
    return cards


def flashcards_csv(entries, cards=None):
    """Anki can import this file: front, back and the note it came from, with no header row."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for meta, body, _ in entries:
        for term, back in glossary_cards(body):
            writer.writerow([term, back, meta["title"]])
        for c in (cards or {}).get(meta.get("id"), []):
            writer.writerow([c["q"], c["a"], meta["title"]])
    return out.getvalue()


def safe_name(title):
    return " ".join(re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", title).split())[:80] or "Note"


def library_zip(entries, source_of, cards=None):
    """Every note as a Markdown file in notes/, plus the flashcards as flashcards.csv."""
    buf = io.BytesIO()
    used = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for meta, body, highlights in entries:
            name = safe_name(meta["title"])
            if name.lower() in used:
                name = f"{name} {meta['id']}"
            used.add(name.lower())
            zf.writestr(f"notes/{name}.md", note_markdown(meta, body, highlights, source_of(meta)))
        zf.writestr("flashcards.csv", flashcards_csv(entries, cards))
    return buf.getvalue()
