import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import library

NOTE = """## TL;DR

Churn is the share of customers who leave each month.

## Key ideas

- Retention matters more than acquisition. [02:10](https://youtu.be/x?t=130)

## Glossary

- **CAC** (customer acquisition cost): what you pay to win one customer.
- **Churn**: the share of customers who leave in a period.
- **PLG**: product-led growth, where the product sells itself.

## Action items

- [ ] Measure churn weekly
"""

INDEX = [
    {"id": "aaaaaaaaaaa", "title": "Growth basics", "channel": "Acme", "created": "2026-01-02T10:00:00"},
    {"id": "bbbbbbbbbbb", "title": "Pricing deep dive", "channel": "Beta", "created": "2026-01-01T10:00:00"},
]
BODIES = {"aaaaaaaaaaa": NOTE, "bbbbbbbbbbb": "## TL;DR\n\nPricing is a product decision.\n"}


class SearchTests(unittest.TestCase):
    def search(self, q):
        return library.search(INDEX, lambda vid: BODIES[vid], q)

    def test_finds_words_in_the_note_text(self):
        hits = self.search("churn")
        self.assertEqual([h["id"] for h in hits], ["aaaaaaaaaaa"])
        self.assertIn("share of customers who leave", hits[0]["snippet"])

    def test_every_word_must_match(self):
        self.assertEqual(self.search("churn pricing"), [])
        self.assertEqual([h["id"] for h in self.search("product decision")], ["bbbbbbbbbbb"])

    def test_title_and_channel_count_as_matches(self):
        self.assertEqual([h["id"] for h in self.search("acme")], ["aaaaaaaaaaa"])

    def test_title_matches_come_first(self):
        index = [{"id": "x" * 11, "title": "Other", "channel": ""}, {"id": "y" * 11, "title": "Growth", "channel": ""}]
        bodies = {"x" * 11: "growth in the text", "y" * 11: "nothing here"}
        hits = library.search(index, bodies.get, "growth")
        self.assertEqual([h["title"] for h in hits], ["Growth", "Other"])

    def test_empty_query_returns_nothing(self):
        self.assertEqual(self.search("   "), [])

    def test_snippet_is_plain_text(self):
        snippet = library.snippet_at("## Key ideas\n\n- **Retention** matters `now`", 20)
        self.assertNotIn("**", snippet)
        self.assertNotIn("`", snippet)

    def test_snippet_shows_link_text_not_its_address(self):
        snippet = library.snippet_at("- Retention [02:10](https://youtu.be/x?t=130) matters", 0)
        self.assertIn("02:10 matters", snippet)
        self.assertNotIn("youtu.be", snippet)


class HighlightTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "highlights.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_add_and_list(self):
        item = library.add_highlight(self.path, "aaaaaaaaaaa", "  Retention matters\n more ", " worth testing ")
        self.assertEqual(item["quote"], "Retention matters more")
        self.assertEqual(item["comment"], "worth testing")
        self.assertEqual(library.highlights_for(self.path, "aaaaaaaaaaa"), [item])
        self.assertEqual(library.highlights_for(self.path, "bbbbbbbbbbb"), [])

    def test_rejects_empty_and_long_text(self):
        with self.assertRaises(ValueError):
            library.add_highlight(self.path, "aaaaaaaaaaa", "   ")
        with self.assertRaises(ValueError):
            library.add_highlight(self.path, "aaaaaaaaaaa", "x" * (library.MAX_TEXT + 1))

    def test_delete_one_highlight(self):
        first = library.add_highlight(self.path, "aaaaaaaaaaa", "one")
        second = library.add_highlight(self.path, "aaaaaaaaaaa", "two")
        self.assertTrue(library.delete_highlight(self.path, "aaaaaaaaaaa", first["id"]))
        self.assertEqual([h["id"] for h in library.highlights_for(self.path, "aaaaaaaaaaa")], [second["id"]])
        self.assertFalse(library.delete_highlight(self.path, "aaaaaaaaaaa", first["id"]))

    def test_drop_removes_all_highlights_of_a_note(self):
        library.add_highlight(self.path, "aaaaaaaaaaa", "one")
        library.add_highlight(self.path, "bbbbbbbbbbb", "two")
        library.drop_highlights(self.path, "aaaaaaaaaaa")
        self.assertEqual(json.loads(self.path.read_text()).keys(), {"bbbbbbbbbbb"})


class ExportTests(unittest.TestCase):
    def test_note_markdown_has_front_matter_and_highlights(self):
        meta = {"title": 'Say "hi": a note', "channel": "Acme", "created": "2026-01-02T10:00:00"}
        highlights = [{"quote": "Retention matters", "comment": "Check this"}, {"quote": "Second", "comment": ""}]
        text = library.note_markdown(meta, NOTE, highlights, "https://youtu.be/aaaaaaaaaaa")
        self.assertTrue(text.startswith('---\ntitle: "Say \\"hi\\": a note"\n'))
        self.assertIn('source: "https://youtu.be/aaaaaaaaaaa"', text)
        self.assertIn("## Your highlights\n\n> Retention matters\n\nCheck this\n\n> Second\n", text)

    def test_note_markdown_without_highlights_has_no_section(self):
        text = library.note_markdown({"title": "T", "id": "a" * 11}, NOTE, [], "s")
        self.assertNotIn("Your highlights", text)

    def test_glossary_cards(self):
        cards = library.glossary_cards(NOTE)
        self.assertEqual(cards, [
            ("CAC", "customer acquisition cost. what you pay to win one customer."),
            ("Churn", "the share of customers who leave in a period."),
            ("PLG", "product-led growth, where the product sells itself."),
        ])

    def test_glossary_cards_ignore_notes_without_glossary(self):
        self.assertEqual(library.glossary_cards("## TL;DR\n\nHello\n"), [])

    def test_flashcards_csv_has_one_row_per_term(self):
        entries = [({"title": "Growth basics"}, NOTE, [])]
        rows = list(csv.reader(io.StringIO(library.flashcards_csv(entries))))
        self.assertEqual(rows[1], ["Churn", "the share of customers who leave in a period.", "Growth basics"])
        self.assertEqual(len(rows), 3)

    def test_library_zip_contains_each_note_and_the_cards(self):
        entries = [
            ({"id": "aaaaaaaaaaa", "title": "A/B: test?", "channel": ""}, NOTE, []),
            ({"id": "bbbbbbbbbbb", "title": "A B  test", "channel": ""}, BODIES["bbbbbbbbbbb"], []),
        ]
        data = library.library_zip(entries, lambda meta: "https://youtu.be/" + meta["id"])
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = sorted(zf.namelist())
            self.assertEqual(names, ["flashcards.csv", "notes/A B test bbbbbbbbbbb.md", "notes/A B test.md"])
            self.assertIn("## Key ideas", zf.read("notes/A B test.md").decode())

    def test_safe_name_removes_path_characters(self):
        self.assertEqual(library.safe_name("a/b\\c:d"), "a b c d")
        self.assertEqual(library.safe_name("   "), "Note")


if __name__ == "__main__":
    unittest.main()
