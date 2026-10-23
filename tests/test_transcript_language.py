import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import transcript
import ytnotes


class TranscriptLanguageTests(unittest.TestCase):
    def test_burmese_original_requests_and_prefers_native_caption(self):
        langs, api_languages = transcript.caption_languages("my")
        self.assertEqual(langs, "my-orig,my,en.*,en")
        self.assertEqual(api_languages, ("my", "en"))
        files = [Path(f"video.{lang}.json3") for lang in ("en", "my", "my-orig")]
        self.assertEqual([p.name for p in transcript.order_caption_files(files, "video", "my")],
                         ["video.my-orig.json3", "video.my.json3", "video.en.json3"])

    def test_other_original_languages_keep_english_first(self):
        langs, api_languages = transcript.caption_languages("fr")
        self.assertEqual(langs, "en.*,en,my-orig,my")
        self.assertEqual(api_languages, ("en", "my"))
        files = [Path(f"video.{lang}.json3") for lang in ("my", "en-US", "en-orig")]
        self.assertEqual([p.name for p in transcript.order_caption_files(files, "video", "fr")],
                         ["video.en-US.json3", "video.en-orig.json3", "video.my.json3"])

    @patch("ytnotes.subprocess.run")
    def test_api_fallback_requests_burmese(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, stdout='[[{"start":0,"text":"မြန်မာ"}]]')
        self.assertEqual(ytnotes.api_transcript("video", "my"), [(0, "မြန်မာ")])
        self.assertEqual(run.call_args.args[0][run.call_args.args[0].index("--languages") + 1], "my")

    def test_burmese_prompts_keep_parser_headings_and_localize_prose(self):
        notes = ytnotes.notes_prompt("my")
        self.assertIn("## TL;DR", notes)
        self.assertIn("## Glossary", notes)
        self.assertIn("clear, natural Burmese", notes)
        self.assertIn("one clear Burmese sentence", notes)
        self.assertNotIn("simple-english skill", notes)

    def test_english_prompts_keep_english_rules(self):
        notes = ytnotes.notes_prompt("en")
        self.assertIn("Write in English.", notes)
        self.assertIn("one clear English sentence", notes)
        self.assertNotIn("clear, natural Burmese", notes)

    def test_add_glossary_uses_note_language(self):
        self.assertIn("Burmese", ytnotes.glossary_prompt("my"))
        self.assertIn('## Glossary', ytnotes.glossary_prompt("my"))
        self.assertIn("English", ytnotes.glossary_prompt("en"))

    @patch("ytnotes.load_index", return_value=[{"id": "video", "language": "my"}])
    def test_burmese_note_audio_fails_clearly(self, _load_index):
        with self.assertRaisesRegex(RuntimeError, "Burmese audio is not supported yet"):
            ytnotes.make_audio("video", "af_heart")


if __name__ == "__main__":
    unittest.main()
