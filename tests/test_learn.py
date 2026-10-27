import json
import tempfile
import unittest
from pathlib import Path

import learn

NOTE = """## TL;DR

Churn is the share of customers who leave each month.

## Glossary

- **CAC** (customer acquisition cost): what you pay to win one customer.
- **Churn**: the share of customers who leave in a period.
"""

REPLY = json.dumps([
    {"q": "What is churn?", "choices": ["Leaving customers", "New customers", "Revenue", "Price"], "answer": 0, "why": "The TL;DR says so."},
    {"q": "What does CAC measure?", "choices": ["Cost to win a customer", "Churn", "Profit", "Price"], "answer": 0, "why": "See the glossary."},
    {"q": "Which matters more?", "choices": ["Retention", "Acquisition", "Logos", "Ads"], "answer": 0, "why": "Retention compounds."},
])


def reverse(items):
    items.reverse()


class ParseQuizTests(unittest.TestCase):
    def test_reads_questions_and_keeps_the_answer_after_shuffling(self):
        questions = learn.parse_quiz("Here you go:\n```json\n" + REPLY + "\n```", shuffle=reverse)
        self.assertEqual(len(questions), 3)
        first = questions[0]
        self.assertEqual(first["choices"], ["Price", "Revenue", "New customers", "Leaving customers"])
        self.assertEqual(first["choices"][first["answer"]], "Leaving customers")
        self.assertEqual(first["why"], "The TL;DR says so.")
        self.assertEqual(len({q["id"] for q in questions}), 3)

    def test_drops_broken_questions(self):
        items = json.loads(REPLY) + [
            {"q": "No choices", "answer": 0},
            {"q": "Bad answer", "choices": ["a", "b"], "answer": 5},
            {"q": "Bool answer", "choices": ["a", "b"], "answer": True},
            {"q": "Same choices", "choices": ["a", "a"], "answer": 0},
            "not an object",
        ]
        self.assertEqual(len(learn.parse_quiz(json.dumps(items))), 3)

    def test_rejects_replies_without_enough_questions(self):
        for reply in ("no json here", "[1, 2", json.dumps(json.loads(REPLY)[:2])):
            with self.assertRaises(ValueError):
                learn.parse_quiz(reply)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "learn.json"
        self.questions = learn.parse_quiz(REPLY, shuffle=lambda x: None)
        learn.save_quiz(self.path, "aaaaaaaaaaa", self.questions)

    def tearDown(self):
        self.dir.cleanup()

    def test_new_questions_replace_the_old_quiz(self):
        self.assertEqual(learn.quiz_for(self.path, "aaaaaaaaaaa")["questions"], self.questions)
        fresh = learn.parse_quiz(REPLY)
        learn.save_quiz(self.path, "aaaaaaaaaaa", fresh)
        self.assertEqual(learn.quiz_for(self.path, "aaaaaaaaaaa")["questions"], fresh)
        self.assertIsNone(learn.quiz_for(self.path, "bbbbbbbbbbb"))

    def test_chat_is_kept_and_cleared(self):
        learn.add_chat(self.path, "aaaaaaaaaaa", {"role": "user", "text": "Why?"}, {"role": "assistant", "text": "Because."})
        self.assertEqual([m["text"] for m in learn.chat_for(self.path, "aaaaaaaaaaa")], ["Why?", "Because."])
        learn.clear_chat(self.path, "aaaaaaaaaaa")
        self.assertEqual(learn.chat_for(self.path, "aaaaaaaaaaa"), [])

    def test_chat_keeps_only_the_latest_messages(self):
        for i in range(learn.MAX_CHAT):
            learn.add_chat(self.path, "aaaaaaaaaaa", {"role": "user", "text": f"q{i}"}, {"role": "assistant", "text": f"a{i}"})
        chat = learn.chat_for(self.path, "aaaaaaaaaaa")
        self.assertEqual(len(chat), learn.MAX_CHAT)
        self.assertEqual(chat[-1]["text"], f"a{learn.MAX_CHAT - 1}")

    def test_drop_note_forgets_the_quiz_and_the_chat(self):
        learn.add_chat(self.path, "aaaaaaaaaaa", {"role": "user", "text": "Why?"})
        learn.add_chat(self.path, "bbbbbbbbbbb", {"role": "user", "text": "How?"})
        learn.drop_note(self.path, "aaaaaaaaaaa")
        data = learn.load(self.path)
        self.assertEqual(data["quizzes"], {})
        self.assertEqual(list(data["chats"]), ["bbbbbbbbbbb"])


class PromptTests(unittest.TestCase):
    def test_chat_input_has_the_note_and_the_conversation(self):
        text = learn.chat_input(NOTE, [{"role": "user", "text": "What is CAC?"}, {"role": "assistant", "text": "A cost."}], "And churn?")
        self.assertTrue(text.startswith("## Notes\n\n## TL;DR"))
        self.assertIn("Reader: What is CAC?\n\nYou: A cost.\n\nReader: And churn?", text)

    def test_prompts_name_the_source(self):
        self.assertIn("an article", learn.quiz_prompt({"kind": "article", "title": "T"}, "Write in English."))
        self.assertIn('a YouTube video, titled "T"', learn.chat_prompt({"title": "T"}, "Write in English."))


if __name__ == "__main__":
    unittest.main()
