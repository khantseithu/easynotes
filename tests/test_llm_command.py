import subprocess
import unittest

import llm


class LlmCommandTests(unittest.TestCase):
    def test_gemini_models_route_to_agy(self):
        self.assertEqual(llm.command("p", "gemini-3.8-flash")[:3], ["agy", "--model", "gemini-3.8-flash"])
        self.assertEqual(llm.command("p", "agy:gemini-3.8-flash-high")[:3], ["agy", "--model", "gemini-3.8-flash-high"])

    def test_other_models_keep_their_cli(self):
        self.assertEqual(llm.command("p", "openai-codex/gpt-6-luna")[0], "pi")
        self.assertEqual(llm.command("p", "sonnet")[0], "claude")

    def test_agy_result_returns_response_text(self):
        out = subprocess.CompletedProcess([], 0, '{"event":"init"}\n{"event":"result","result":{"status":"SUCCESS","response":"Notes\\n"}}\n', "")
        res = llm.agy_result(out)
        self.assertEqual((res.returncode, res.stdout), (0, "Notes\n"))

    def test_agy_result_reports_errors(self):
        out = subprocess.CompletedProcess([], 0, '{"event":"result","result":{"status":"ERROR","response":"","error":"quota"}}\n', "")
        res = llm.agy_result(out)
        self.assertEqual((res.returncode, res.stdout, res.stderr), (1, "", "quota"))


if __name__ == "__main__":
    unittest.main()
