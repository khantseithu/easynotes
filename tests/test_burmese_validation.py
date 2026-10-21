import subprocess
import unittest
from unittest.mock import patch

import llm
import transcript


class BurmeseValidationTests(unittest.TestCase):
    @patch("llm.subprocess.run")
    def test_generic_run_without_model_uses_luna(self, process_run):
        process_run.return_value = subprocess.CompletedProcess([], 0, stdout="ok", stderr="")
        llm.run("prompt", None)
        self.assertEqual(process_run.call_args.args[0][process_run.call_args.args[0].index("--model") + 1],
                         llm.DEFAULT_MODEL)

    @patch("llm.subprocess.run")
    def test_burmese_default_uses_sol_for_initial_and_repair(self, process_run):
        process_run.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="မြန်မာ текст", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="မြန်မာ Python API", stderr=""),
        ]
        result = llm.run_burmese("Write notes", None, "source", "source")
        self.assertEqual(result.stdout, "မြန်မာ Python API")
        self.assertEqual(process_run.call_count, 2)
        for call in process_run.call_args_list:
            self.assertEqual(call.args[0][call.args[0].index("--model") + 1], llm.BURMESE_MODEL)

    @patch("llm.subprocess.run")
    def test_explicit_luna_is_kept_for_burmese(self, process_run):
        process_run.return_value = subprocess.CompletedProcess([], 0, stdout="မြန်မာ Python API", stderr="")
        llm.run_burmese("Write notes", llm.DEFAULT_MODEL, "source", "source")
        self.assertEqual(process_run.call_args.args[0][process_run.call_args.args[0].index("--model") + 1],
                         llm.DEFAULT_MODEL)

    def test_language_defaults_and_explicit_model_override(self):
        self.assertEqual(llm.model_for_language("en"), "openai-codex/gpt-6-luna")
        self.assertEqual(llm.model_for_language("my"), "openai-codex/gpt-6.1-sol")
        self.assertEqual(llm.model_for_language("Burmese"), "openai-codex/gpt-6.1-sol")
        self.assertEqual(llm.model_for_language("my", "openai-codex/gpt-6-luna"),
                         "openai-codex/gpt-6-luna")

    def test_burmese_and_latin_technical_terms_are_valid(self):
        output = "## TL;DR\nPython API ကို အသုံးပြုသည်။"
        self.assertTrue(transcript.valid_burmese_output(output))

    def test_source_grounded_cyrillic_is_allowed(self):
        source = "The speaker quoted Привет once."
        self.assertTrue(transcript.valid_burmese_output("## TL;DR မြန်မာ\nПривет", source))

    def test_foreign_words_with_same_initial_are_not_source_grounded(self):
        source = "The speaker quoted Привет once."
        self.assertFalse(transcript.valid_burmese_output("မြန်မာ Пока", source))

    def test_unrelated_scripts_are_rejected_and_source_names_are_allowed(self):
        self.assertFalse(transcript.valid_burmese_output("မြန်မာ 中文"))
        self.assertFalse(transcript.valid_burmese_output("မြန်မာ ภาษาไทย"))
        self.assertFalse(transcript.valid_burmese_output("Only English API notes"))
        self.assertTrue(transcript.valid_burmese_output("မြန်မာ 東京", "Source mentions 東京"))
        self.assertTrue(transcript.valid_burmese_output(""))

    def test_unmatched_cyrillic_and_drafting_remarks_are_rejected(self):
        self.assertFalse(transcript.valid_burmese_output("မြန်မာ текст"))
        self.assertFalse(transcript.valid_burmese_output("မြန်မာ (Wait Burmese typo foreign). Need fix."))
        self.assertFalse(transcript.valid_burmese_output("မြန်မာ (Fix Burmese)"))

    @patch("llm.run")
    def test_invalid_draft_is_repaired_once(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="မြန်မာ текст", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="မြန်မာ Python API", stderr=""),
        ]
        result = llm.run_burmese("Write notes", "model", "source", "source")
        self.assertEqual(result.stdout, "မြန်မာ Python API")
        self.assertEqual(run.call_count, 2)
        self.assertIn("Draft to repair\nမြန်မာ текст", run.call_args.args[2])

    @patch("llm.run")
    def test_invalid_repair_fails_instead_of_returning_corruption(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="текст", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="still текст (Fix Burmese)", stderr=""),
        ]
        with self.assertRaisesRegex(RuntimeError, "failed validation after one repair"):
            llm.run_burmese("Write notes", "model", "source", "source")
        self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
