import unittest

import ytnotes


class LevelTests(unittest.TestCase):
    def test_each_level_sets_its_length_rule(self):
        for language in ("en", "my"):
            normal = ytnotes.notes_prompt(language).format(title="T", channel="C", duration="1h")
            detailed = ytnotes.notes_prompt(language, "detailed").format(title="T", channel="C", duration="1h")
            self.assertIn("about 300 words", normal)
            self.assertNotIn("Write detailed notes", normal)
            self.assertIn("Write detailed notes", detailed)
            self.assertIn("about 4000", detailed)
            self.assertNotIn("{length}", detailed)


if __name__ == "__main__":
    unittest.main()
