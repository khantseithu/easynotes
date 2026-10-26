"""Quizzes, spaced review and chat: what helps the reader remember a note after reading it."""
import json
import random
import re
import threading
import uuid
from datetime import date, datetime, timedelta

import library

LOCK = threading.Lock()
MAX_QUESTION = 1000
MAX_CHAT = 40
FIRST_EASE = 2.5
MIN_EASE = 1.3

QUIZ_PROMPT = """The notes on stdin were written from {source}. Write a quiz that shows whether the reader understood and remembers them.

Write {count} multiple-choice questions. Each question tests one important idea, framework, number or step from the notes, not a small detail.
Ask about meaning and use, not only wording, for example "Why ...", "What happens when ..." or "Which of these is an example of ...".
Each question has 4 answer choices, and exactly one is correct. The wrong choices must seem right to someone who only skimmed the notes,
and be about as long as the correct one. Never use "all of the above" or "none of the above". Use only facts that are in the notes.

Reply with only a JSON array, with no code fence and no other text. Each item is an object with these keys:
- "q": the question.
- "choices": an array of 4 strings.
- "answer": the index (0 to 3) of the correct choice.
- "why": one sentence that says why the answer is correct, based on the notes.

{language}"""

CHAT_PROMPT = """You help a reader understand notes that they read. The notes were written from {source}, titled "{title}".
The notes and the conversation so far are on stdin.

Answer the reader's last question in a few short sentences or bullets. Use the notes first.
If the notes do not cover the question, say so in one sentence, then answer from general knowledge and say that this part is not from the notes.
Never invent what the speaker or the author said. Use markdown, but no headings. Output only the answer.

{language}"""

BURMESE_RULES = """Write in clear, natural Burmese for a Burmese reader. Keep Latin text only for names, technical terms, code and numbers.
Do not add drafting, translation or self-review remarks."""


def source_name(meta):
    return "an article" if meta.get("kind") == "article" else "a YouTube video"


def quiz_prompt(meta, language_rules, count=6):
    return QUIZ_PROMPT.format(source=source_name(meta), count=count, language=language_rules)


def chat_prompt(meta, language_rules):
    return CHAT_PROMPT.format(source=source_name(meta), title=meta["title"], language=language_rules)


def chat_input(md, messages, question):
    turns = [f"{'Reader' if m['role'] == 'user' else 'You'}: {m['text']}" for m in messages[-10:]]
    return f"## Notes\n\n{md}\n\n## Conversation\n\n" + "\n\n".join([*turns, f"Reader: {question}"])


def parse_quiz(text, shuffle=random.shuffle):
    """The valid questions in the model's reply. The choices are shuffled, because models favour one position."""
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        raise ValueError("The quiz reply has no questions")
    try:
        items = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError("The quiz reply is not valid JSON") from e
    questions = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        q, choices, answer = item.get("q"), item.get("choices"), item.get("answer")
        if not isinstance(q, str) or not q.strip() or not isinstance(choices, list) or len(choices) < 2:
            continue
        if not all(isinstance(c, str) and c.strip() for c in choices) or len({c.strip() for c in choices}) < len(choices):
            continue
        if isinstance(answer, bool) or not isinstance(answer, int) or not 0 <= answer < len(choices):
            continue
        correct = choices[answer].strip()
        order = [c.strip() for c in choices]
        shuffle(order)
        why = item.get("why") if isinstance(item.get("why"), str) else ""
        questions.append({"id": uuid.uuid4().hex[:6], "q": q.strip()[:MAX_QUESTION], "choices": order,
                          "answer": order.index(correct), "why": why.strip()[:MAX_QUESTION]})
    if len(questions) < 3:
        raise ValueError("The quiz reply has too few usable questions")
    return questions


def load(path):
    data = json.loads(path.read_text()) if path.exists() else {}
    return {"quizzes": data.get("quizzes", {}), "cards": data.get("cards", {}), "chats": data.get("chats", {})}


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def quiz_for(path, vid):
    return load(path)["quizzes"].get(vid)


def save_quiz(path, vid, questions):
    quiz = {"created": datetime.now().isoformat(timespec="seconds"), "questions": questions}
    with LOCK:
        data = load(path)
        old = {q["id"] for q in (data["quizzes"].get(vid) or {}).get("questions", [])}
        # New questions replace the old ones, so their review cards go too.
        data["cards"] = {k: c for k, c in data["cards"].items() if not (c["note"] == vid and c["ref"] in old and c["kind"] == "quiz")}
        data["quizzes"][vid] = quiz
        save(path, data)
    return quiz


def card_id(vid, kind, ref):
    return f"{vid}:{kind}:{ref}"


def schedule(card, correct, today):
    """A short form of SM-2: each right answer makes the gap longer, and a wrong answer starts it again."""
    card = {"interval": 0, "ease": FIRST_EASE, "reps": 0, "lapses": 0, **card}
    if correct:
        card["reps"] += 1
        card["interval"] = 1 if card["reps"] == 1 else 3 if card["reps"] == 2 else max(card["interval"] + 1, round(card["interval"] * card["ease"]))
    else:
        card["reps"] = 0
        card["interval"] = 1
        card["lapses"] += 1
        card["ease"] = max(MIN_EASE, round(card["ease"] - 0.2, 2))
    card["due"] = (today + timedelta(days=card["interval"])).isoformat()
    card["last"] = today.isoformat()
    return card


def enroll(path, vid, answers, terms, today=None):
    """Add a note to review after its quiz: each question, scheduled by the answer, and each glossary term.

    answers maps question ids to True or False. Cards that are already in review keep their schedule.
    """
    today = today or date.today()
    with LOCK:
        data = load(path)
        quiz = data["quizzes"].get(vid) or {"questions": []}
        for q in quiz["questions"]:
            key = card_id(vid, "quiz", q["id"])
            if key not in data["cards"] and q["id"] in answers:
                data["cards"][key] = schedule({"note": vid, "kind": "quiz", "ref": q["id"]}, bool(answers[q["id"]]), today)
        for term in terms:
            key = card_id(vid, "term", term)
            if key not in data["cards"]:
                data["cards"][key] = {"note": vid, "kind": "term", "ref": term, "interval": 0, "ease": FIRST_EASE,
                                      "reps": 0, "lapses": 0, "due": (today + timedelta(days=1)).isoformat()}
        save(path, data)
    return stats(path, today)


def in_review(path, vid):
    return any(c["note"] == vid for c in load(path)["cards"].values())


def card_view(key, card, data, notes, read_text):
    """What the review screen shows for a card, or None when its note, question or term is gone."""
    meta = notes.get(card["note"])
    if not meta:
        return None
    base = {"id": key, "kind": card["kind"], "note": card["note"], "title": meta["title"], "language": meta.get("language", "en")}
    if card["kind"] == "quiz":
        q = next((q for q in (data["quizzes"].get(card["note"]) or {}).get("questions", []) if q["id"] == card["ref"]), None)
        return q and {**base, **{k: q[k] for k in ("q", "choices", "answer", "why")}}
    back = dict(library.glossary_cards(read_text(card["note"]))).get(card["ref"])
    return back and {**base, "term": card["ref"], "back": back}


def due(path, notes, read_text, today=None, limit=40):
    """The cards to review today, oldest first."""
    today = (today or date.today()).isoformat()
    data = load(path)
    notes = {n["id"]: n for n in notes}
    out = []
    for key, card in sorted(data["cards"].items(), key=lambda kc: (kc[1]["due"], kc[0])):
        if card["due"] > today:
            break
        view = card_view(key, card, data, notes, read_text)
        if view:
            out.append(view)
        if len(out) >= limit:
            break
    return out


def answer(path, key, correct, today=None):
    today = today or date.today()
    with LOCK:
        data = load(path)
        if key not in data["cards"]:
            return None
        data["cards"][key] = schedule(data["cards"][key], correct, today)
        save(path, data)
        return data["cards"][key]


def stats(path, today=None, notes=None):
    """How many cards are due today, how many there are, and when the next one is due."""
    today = (today or date.today()).isoformat()
    cards = load(path)["cards"].values()
    if notes is not None:
        ids = {n["id"] for n in notes}
        cards = [c for c in cards if c["note"] in ids]
    later = sorted(c["due"] for c in cards if c["due"] > today)
    return {"due": sum(c["due"] <= today for c in cards), "total": len(cards), "next": later[0] if later else None}


def chat_for(path, vid):
    return load(path)["chats"].get(vid, [])


def add_chat(path, vid, *messages):
    stamp = datetime.now().isoformat(timespec="seconds")
    with LOCK:
        data = load(path)
        chat = [*data["chats"].get(vid, []), *({**m, "at": stamp} for m in messages)][-MAX_CHAT:]
        data["chats"][vid] = chat
        save(path, data)
    return chat


def clear_chat(path, vid):
    with LOCK:
        data = load(path)
        if data["chats"].pop(vid, None) is not None:
            save(path, data)


def drop_note(path, vid):
    """Forget the quiz, the review cards and the chat of a deleted note."""
    with LOCK:
        data = load(path)
        data["quizzes"].pop(vid, None)
        data["chats"].pop(vid, None)
        data["cards"] = {k: c for k, c in data["cards"].items() if c["note"] != vid}
        if path.exists():
            save(path, data)
