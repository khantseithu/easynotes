import json
import tempfile
import unittest
from datetime import date, timedelta
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
TODAY = date(2026, 10, 26)
INDEX = [{"id": "aaaaaaaaaaa", "title": "Growth basics", "channel": "Acme"}]


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


class ScheduleTests(unittest.TestCase):
    def test_right_answers_space_the_card_out(self):
        card = {"note": "a", "kind": "quiz", "ref": "q"}
        gaps = []
        for _ in range(4):
            card = learn.schedule(card, True, TODAY)
            gaps.append(card["interval"])
        self.assertEqual(gaps, [1, 3, 8, 20])
        self.assertEqual(card["due"], (TODAY + timedelta(days=20)).isoformat())

    def test_a_wrong_answer_starts_again_and_lowers_the_ease(self):
        card = learn.schedule(learn.schedule({}, True, TODAY), True, TODAY)
        card = learn.schedule(card, False, TODAY)
        self.assertEqual((card["interval"], card["reps"], card["lapses"]), (1, 0, 1))
        self.assertEqual(card["ease"], 2.3)
        for _ in range(20):
            card = learn.schedule(card, False, TODAY)
        self.assertEqual(card["ease"], learn.MIN_EASE)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "learn.json"
        self.questions = learn.parse_quiz(REPLY, shuffle=lambda x: None)
        learn.save_quiz(self.path, "aaaaaaaaaaa", self.questions)

    def tearDown(self):
        self.dir.cleanup()

    def answers(self, *right):
        return {q["id"]: ok for q, ok in zip(self.questions, right)}

    def test_enroll_adds_questions_and_terms(self):
        stats = learn.enroll(self.path, "aaaaaaaaaaa", self.answers(True, False, True), ["CAC", "Churn"], TODAY)
        self.assertEqual(stats, {"due": 0, "total": 5, "next": "2026-10-27"})
        self.assertTrue(learn.in_review(self.path, "aaaaaaaaaaa"))
        self.assertFalse(learn.in_review(self.path, "bbbbbbbbbbb"))

    def test_enroll_keeps_the_schedule_of_cards_in_review(self):
        learn.enroll(self.path, "aaaaaaaaaaa", self.answers(True, True, True), [], TODAY)
        key = learn.card_id("aaaaaaaaaaa", "quiz", self.questions[0]["id"])
        learn.answer(self.path, key, True, TODAY + timedelta(days=1))
        learn.enroll(self.path, "aaaaaaaaaaa", self.answers(False, False, False), [], TODAY + timedelta(days=1))
        self.assertEqual(learn.load(self.path)["cards"][key]["reps"], 2)

    def test_due_cards_show_the_question_or_the_term(self):
        learn.enroll(self.path, "aaaaaaaaaaa", self.answers(True, True, True), ["CAC", "Gone"], TODAY)
        cards = learn.due(self.path, INDEX, lambda vid: NOTE, TODAY + timedelta(days=1))
        kinds = sorted(c["kind"] for c in cards)
        # "Gone" is no longer in the glossary, so it is left out.
        self.assertEqual(kinds, ["quiz", "quiz", "quiz", "term"])
        term = next(c for c in cards if c["kind"] == "term")
        self.assertEqual((term["term"], term["back"], term["title"]), ("CAC", "customer acquisition cost. what you pay to win one customer.", "Growth basics"))
        quiz = next(c for c in cards if c["kind"] == "quiz")
        self.assertIn(quiz["q"], [q["q"] for q in self.questions])
        self.assertEqual(learn.due(self.path, INDEX, lambda vid: NOTE, TODAY), [])

    def test_answer_moves_the_card(self):
        learn.enroll(self.path, "aaaaaaaaaaa", self.answers(True, True, True), [], TODAY)
        key = learn.card_id("aaaaaaaaaaa", "quiz", self.questions[0]["id"])
        card = learn.answer(self.path, key, True, TODAY + timedelta(days=1))
        self.assertEqual(card["due"], "2026-10-30")
        self.assertIsNone(learn.answer(self.path, "missing", True, TODAY))

    def test_new_questions_replace_the_old_cards(self):
        learn.enroll(self.path, "aaaaaaaaaaa", self.answers(True, True, True), ["CAC"], TODAY)
        learn.save_quiz(self.path, "aaaaaaaaaaa", learn.parse_quiz(REPLY))
        self.assertEqual([c["kind"] for c in learn.load(self.path)["cards"].values()], ["term"])

    def test_stats_leave_out_deleted_notes(self):
        learn.enroll(self.path, "aaaaaaaaaaa", self.answers(True, True, True), [], TODAY)
        self.assertEqual(learn.stats(self.path, TODAY, notes=[])["total"], 0)

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

    def test_drop_note_forgets_everything(self):
        learn.enroll(self.path, "aaaaaaaaaaa", self.answers(True, True, True), ["CAC"], TODAY)
        learn.add_chat(self.path, "aaaaaaaaaaa", {"role": "user", "text": "Why?"})
        learn.drop_note(self.path, "aaaaaaaaaaa")
        self.assertEqual(learn.load(self.path), {"quizzes": {}, "cards": {}, "chats": {}})


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
