"""Quizzes and questions about a note: ways to check and deepen what the reader understood."""
import json
import random
import re
import threading
import uuid
from datetime import datetime

LOCK = threading.Lock()
MAX_QUESTION = 1000
MAX_CHAT = 40

QUIZ_PROMPT = """The notes on stdin were written from {source}. Write a quiz that shows whether the reader understood them.

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
    return {"quizzes": data.get("quizzes", {}), "chats": data.get("chats", {})}


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def quiz_for(path, vid):
    return load(path)["quizzes"].get(vid)


def save_quiz(path, vid, questions):
    quiz = {"created": datetime.now().isoformat(timespec="seconds"), "questions": questions}
    with LOCK:
        data = load(path)
        data["quizzes"][vid] = quiz
        save(path, data)
    return quiz


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
    """Forget the quiz and the chat of a deleted note."""
    with LOCK:
        data = load(path)
        found = [data[key].pop(vid, None) for key in ("quizzes", "chats")]
        if any(x is not None for x in found):
            save(path, data)
