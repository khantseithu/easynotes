import csv
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path

import library

TODAY = date(2026, 10, 27)
OUTPUT = """Here are your cards:

Q: Why does retention matter more than acquisition?
A: Lost customers cancel out the ones you win.

**Q:** How often should you measure churn?
**A:** Every week.

Q: A question with no answer
"""


class FlashcardTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "flashcards.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_parse_cards_reads_question_answer_pairs(self):
        self.assertEqual(library.parse_cards(OUTPUT), [
            ("Why does retention matter more than acquisition?", "Lost customers cancel out the ones you win."),
            ("How often should you measure churn?", "Every week."),
        ])

    def test_new_cards_are_due_today(self):
        library.set_cards(self.path, "aaaaaaaaaaa", library.parse_cards(OUTPUT), TODAY)
        notes = [{"id": "aaaaaaaaaaa", "title": "Growth"}]
        due = library.due_cards(self.path, notes, TODAY)
        self.assertEqual(len(due["cards"]), 2)
        self.assertEqual(due["cards"][0]["title"], "Growth")
        self.assertIsNone(due["next_due"])

    def test_schedule_spaces_correct_answers_and_resets_misses(self):
        card = {"id": "c", "q": "q", "a": "a", "due": TODAY.isoformat(), "interval": 0, "ease": 2.5, "reps": 0}
        card = library.schedule(card, "good", TODAY)
        self.assertEqual((card["interval"], card["due"]), (1, "2026-10-28"))
        card = library.schedule(card, "good", TODAY)
        self.assertEqual(card["interval"], 3)
        card = library.schedule(card, "good", TODAY)
        self.assertEqual(card["interval"], 8)
        card = library.schedule(card, "again", TODAY)
        self.assertEqual((card["interval"], card["reps"], card["due"]), (0, 0, TODAY.isoformat()))
        self.assertEqual(card["ease"], 2.3)
        self.assertGreaterEqual(library.schedule(card, "easy", TODAY)["interval"], 4)

    def test_reviewed_cards_leave_the_due_list(self):
        cards = library.set_cards(self.path, "aaaaaaaaaaa", [("q1", "a1"), ("q2", "a2")], TODAY)
        library.review_card(self.path, "aaaaaaaaaaa", cards[0]["id"], "good", TODAY)
        due = library.due_cards(self.path, [{"id": "aaaaaaaaaaa", "title": "T"}], TODAY)
        self.assertEqual([c["q"] for c in due["cards"]], ["q2"])
        self.assertEqual(due["next_due"], "2026-10-28")
        with self.assertRaises(ValueError):
            library.review_card(self.path, "aaaaaaaaaaa", cards[1]["id"], "hard", TODAY)

    def test_due_cards_skip_deleted_notes_and_filter_by_note(self):
        library.set_cards(self.path, "aaaaaaaaaaa", [("q1", "a1")], TODAY)
        library.set_cards(self.path, "bbbbbbbbbbb", [("q2", "a2")], TODAY)
        notes = [{"id": "aaaaaaaaaaa", "title": "A"}]
        self.assertEqual([c["q"] for c in library.due_cards(self.path, notes, TODAY)["cards"]], ["q1"])
        notes.append({"id": "bbbbbbbbbbb", "title": "B"})
        self.assertEqual([c["q"] for c in library.due_cards(self.path, notes, TODAY, "bbbbbbbbbbb")["cards"]], ["q2"])

    def test_flashcards_csv_includes_ai_cards(self):
        entries = [({"id": "aaaaaaaaaaa", "title": "Growth"}, "## TL;DR\n\nx\n", [])]
        cards = {"aaaaaaaaaaa": [{"q": "Why?", "a": "Because."}]}
        rows = list(csv.reader(io.StringIO(library.flashcards_csv(entries, cards))))
        self.assertEqual(rows, [["Why?", "Because.", "Growth"]])


if __name__ == "__main__":
    unittest.main()
